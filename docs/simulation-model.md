# How Amber's simulator works

Amber answers one question: *if I build my system this way and send it this much traffic, what
happens?* It answers it by pretending to run the system — one imaginary request at a time, thousands
of them — and writing down what each one did. This page explains how, in plain English. The formal
spec is §8 of the implementation plan; the code is `backend/amber/sim/`.

## The clock (`sim/kernel.py`)

Real time is continuous. Simulated time is not: nothing in a simulated system changes except at
particular moments — a request arrives, a database query finishes, a slot frees up. So instead of
ticking forward a millisecond at a time and finding that nothing happened, Amber keeps a list of
*scheduled events* and jumps straight to the next one. Sixty seconds of traffic take a tenth of a
second of real time, because only the interesting moments cost anything.

Everything else follows from that:

- **Time is a float in milliseconds** and only ever goes forward.
- **Events** sit on a heap ordered by `(time, sequence number)`. The sequence number matters more
  than it looks: when two events are due at the same instant, it makes them run in the order they
  were scheduled, every time, on every machine. Without it the order would depend on memory
  addresses and no two runs would agree.
- A **process** is a Python generator. It does some work, says `yield Timeout(env, 40)` to mean "this
  takes 40 ms", and is resumed 40 simulated milliseconds later. A request moving through the design
  is one such process, and a node calling a downstream node is `yield from` into another generator.
- A **resource** is a pool of slots with one FIFO line in front: a service replica's worker threads,
  a database's connection pool. Asking for a slot returns an event that fires when the slot is yours,
  or nothing at all when the line is already at its limit — which is the model's version of a 503.
  Each resource keeps a running total of *slot-milliseconds busy*, which is where utilization comes
  from later.

## The dice (`sim/rng.py`)

Every random number is reproducible. Each node draws from its own generator, seeded with the SHA-256
of `(run seed, node id, purpose)`. Two consequences worth knowing:

- **The same design, config and seed always give exactly the same result**, on any machine, in any
  process. Python's built-in `hash()` is deliberately never used for seeding: it is salted per
  process, so it would silently break this.
- **Purposes are separated** (`arrivals`, `work`, `hit`, `tokens`, `accept`, `retry`). Adding a coin
  flip in the cache doesn't shift the service's work times, so a change to one part of the model
  doesn't scramble every number in the result.

Latencies are **lognormal**, specified by a median and a 99th percentile — the two numbers people
actually have from their dashboards. A lognormal is the exponential of a normal distribution: mostly
clustered, with a long right tail, which is what request latencies look like in practice. The
conversion is `mu = ln(p50)` and `sigma = (ln(p99) − ln(p50)) / 2.3263479`, where 2.3263479 is how
many standard deviations above the median the 99th percentile sits.

## Traffic (`sim/arrivals.py`)

Arrivals are a **Poisson process**: requests come independently, at an average rate, with random gaps.
That is what independent users look like from the server's side, and it is the standard assumption
queueing theory is built on.

The rate is allowed to change over time (constant, a spike, or a ramp), which is handled by
**thinning**: generate candidate arrivals at the profile's *highest* rate, then keep each one with
probability `rate(t) / peak`. What survives follows the profile exactly, without any cleverness about
integrating the rate curve.

Traffic is **open-loop**: users keep arriving at the set rate no matter how slow the system gets.
Real users would give up and stop clicking, which relieves an overloaded system; Amber does not model
that, so an overload looks worse here than it might in reality. That is the right direction to be
wrong in for a capacity-planning tool.

## The nodes (`sim/nodes/`)

A request walks the graph, and every node it touches leaves a **span**: how long it waited there, and
how long that node's own work took. Calls are **synchronous** — a caller waits for everything
downstream before it continues.

| Node | What it does |
|---|---|
| **Users** | Creates requests on the traffic schedule and decides each one's final status at the end: `ok`, or `timeout` if it came back after the client gave up. |
| **Load balancer** | A small overhead, then picks a target: round robin, or the target with the fewest requests currently in flight. |
| **Service** | `replicas × concurrencyPerReplica` worker slots, each replica with its own line. A request holds its slot for its own work *and* for every downstream call, in edge order — thread-per-request, so a slow database makes the service look busy too. Over the queue limit, the request is rejected. |
| **Cache** | Every lookup costs its latency; a hit (probability `hitRate`) answers there, a miss continues down the single outgoing edge. |
| **Database** | A connection pool with a waiting line, then the query time. Nothing downstream. |
| **Agent** | Makes `1 + Poisson(llmCallsMean − 1)` LLM calls per request, so always at least one. Call *i* (counting from 0) sends `basePromptTokens + i × contextGrowthTokensPerStep` prompt tokens, because every step re-sends the conversation so far; that growth is where an agent's cost comes from. Between two LLM calls, never after the last, it makes `toolCallsPerStep` tool calls one after another: to its tool edges round robin (starting over with each request), or, with no tool edges, a `toolLatency` wait. Its own span is that wait time. No capacity limit of its own: it runs in its caller's slot. |
| **Hosted LLM** | Waits for the first token, then streams the rest at a sampled tokens-per-second. A bucket of rate-limit permits refills continuously; a call that finds it empty gets a 429, backs off (`500 × 2^attempt` ms, capped at 8 s, plus jitter) and retries, and after the last retry the request fails as `rate_limited`. Cost accrues per prompt and output token. |

Errors are statuses, not exceptions. A node that fails a request sets its status and returns; every
caller checks, stops its remaining downstream calls, releases what it is holding, and returns too. A
request keeps the first error that happened to it.

*Not yet built:* the self-hosted LLM scheduler (continuous batching, KV-cache admission, speculative
decoding). Designs using it are refused rather than approximated.

## Measurement (`sim/metrics.py`)

Everything is bucketed into **one simulated second**. A small process wakes at the end of each bucket
and reads every node's counters; requests are sorted into buckets afterwards — an arrival into the
bucket it was created in, an outcome into the bucket it ended in.

- **Utilization** is `busy slot-ms / (slots × bucket ms)`. It is never clamped to 100%: a value above
  1 would mean a bug in the model, and hiding it would hide the bug.
- **Warmup** (5 s by default) is left out of the summary, because a system that starts empty flatters
  itself, but it stays in the timeline so you can see the ramp.
- **The summary follows requests, not seconds.** It covers the requests that arrived after warmup, each
  counted once with its own outcome — the way a load test counts the requests it sends. A request that
  arrived during warmup never enters it, even if it finishes later. So requests = succeeded + failed +
  timed out + still running when the run ended. The timeline instead counts each outcome in the second
  it happened, which is what a throughput-over-time chart needs.
- **Downsampling**: the timeline is capped at 300 points, so runs longer than 300 s merge buckets in
  pairs. A merged point keeps the underlying counts and latency values, so its rates are true totals
  over its full width and its percentiles come from all of its latencies — not from averaging each
  bucket's percentiles. (§8.8 allowed the cheaper approximation of taking the maximum of merged p99s;
  the exact version turned out to be no more work.)

## Explanation (`sim/analysis.py`, `sim/cost.py`)

**Attribution** takes the slowest 1% of answered requests, pools their spans by node, and reports each
node's share of that time, split into waiting and working. It answers "when it's slow, where is the
time going?" rather than "what is the average".

**Bottlenecks** are a short ordered list of plain-English findings with numbers in them: a node above
90% busy, a queue that keeps growing, rejections, rate-limit hits, a GPU out of KV cache, or — when
none of that is true — a line saying so and quoting the p99. At most five, most severe first.

**Cost** is monthly. Services, caches and databases carry flat prices; self-hosted GPUs are
`replicas × $/hour × 730`. A hosted LLM is different, because it bills per token: what the simulated
window actually spent is scaled up to 30 days, which assumes the simulated traffic pattern repeats
all month. Every price comes from a preset marked *verify* — treat all of it as an estimate.

## Is any of this right?

`backend/tests/sim/test_queueing_theory.py` is the check that matters. Queueing theory gives exact
answers for simple systems, so Amber is pointed at two of them and has to agree within 5%:

- **M/M/1** — one server, requests arriving 7/s, served 10/s. Theory says the average wait in line is
  `ρ/(μ−λ)` = 233 ms. The simulator, averaged over 100 independent 600-second runs, is within a
  fraction of a percent.
- **M/M/c** — two servers sharing one line, 15/s in, 10/s each. Erlang C says 128.6 ms. Same result.

The tolerance is fixed at 5% on purpose. If one of these ever drifts, the fix is a longer run or more
replications — never a wider bound, which would quietly turn the project's central claim into a
formality. Alongside them, `test_determinism.py` proves the same inputs give byte-identical JSON
(across processes with different hash seeds, too), and `test_perf.py` holds the speed targets: about
12,000 requests in well under 2 s, and the 200,000-request cap in well under 15 s.

## Known simplifications

All of these are deliberate. They are listed in the app under "Model assumptions" as well.

1. **Open-loop traffic.** Users keep arriving at the set rate however slow the system gets.
2. **Synchronous calls.** A caller waits for everything downstream; no fire-and-forget, no queues
   between services.
3. **Thread-per-request services.** A slot is held for the whole request, downstream calls included.
4. **No separate network latency.** Fold it into each node's latency settings.
5. **No preemption for self-hosted LLMs.** Once a request is admitted it keeps its KV cache; requests
   that don't fit wait. Real vLLM pages and preempts.
6. **Linear prefill and decode timing.** Both grow linearly with tokens and batch size.
7. **Hosted APIs have unlimited concurrency.** Only the rate limit turns requests away.
8. **Monthly cost is extrapolated** from the simulated window, as if that traffic ran all month.
9. **One queue discipline: FIFO.** No priorities, no retries between your own services, no circuit
   breakers.
10. **The run stops at its duration.** Requests still running then have no outcome and no latency,
    so the summary leaves them out of the percentiles (it reports how many there were).
