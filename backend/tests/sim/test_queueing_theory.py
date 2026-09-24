"""The simulator against textbook queueing theory (plan §16): the claim the whole project rests on.

A queue of random work has exact formulas for how long the line gets. If the simulator disagrees with
them, nothing it says about anyone's system is worth reading. So: drive a service node with Poisson
arrivals and exponential work, measure the mean time requests spend *waiting for a slot*, and compare
it with the formula. Both cases must land within 5%.

Exponential work is the point: the formulas below assume it, while Amber's services normally draw
lognormal times from p50/p99. `run.execute` takes a work sampler for exactly this, and it is a
keyword argument rather than a contract field, so it can never appear in the API or its schema.

**The 5% tolerance is not negotiable.** If one of these ever drifts, the fix is a longer run or more
replications — never a wider bound, which would turn the project's central claim into a formality.

Precision: one 600 s run of the M/M/1 case has a standard deviation of about 15% around the true mean
(waits in a queue are strongly correlated, so a single run is one noisy sample, not 4,000 independent
ones). Averaging REPLICATIONS independent runs brings that down to roughly 1.5%, which leaves the 5%
bound real headroom. Measured over seed blocks 1-100, 101-200, 201-300 and 301-400, every block lands
within 1.6% of theory.
"""

import random
import statistics

import pytest

from amber.contracts import Design, RunConfig
from amber.sim.run import execute

REPLICATIONS = 100  # independent runs, averaged: see the precision note above
DURATION_S = 600  # the longest run RunConfig allows
WARMUP_S = 30  # the system starts empty, which flatters it; ignore requests that arrive this early
MU_PER_S = 10  # one server finishes 10 requests a second, so mean work is 100 ms


def test_mm1_mean_wait_matches_theory(request):
    """One server, λ = 7/s, μ = 10/s."""
    # ρ = λ/μ = 7/10 = 0.7
    # Wq = ρ / (μ − λ) = 0.7 / (10 − 7) = 0.7 / 3 = 0.23333… s = 233.3 ms
    theory_ms = 233.3
    measured_ms = mean_wait_ms(arrival_rps=7, servers=1)
    _report(request, "M/M/1 (λ=7, μ=10)", measured_ms, theory_ms)
    assert measured_ms == pytest.approx(theory_ms, rel=0.05)


def test_mmc_mean_wait_matches_erlang_c(request):
    """Two servers sharing one line, λ = 15/s, μ = 10/s."""
    # a = λ/μ = 1.5 servers' worth of work; c = 2 servers; ρ = λ/(cμ) = 15/20 = 0.75
    # Erlang B by its recursion, B(0, a) = 1:
    #   B(1, a) = a·B(0)/(1 + a·B(0)) = 1.5/2.5 = 0.6
    #   B(2, a) = a·B(1)/(2 + a·B(1)) = 0.9/2.9 = 0.310345
    # Erlang C = B / (1 − ρ(1 − B)) = 0.310345 / (1 − 0.75·0.689655)
    #          = 0.310345 / 0.482759 = 0.642857
    # Wq = C / (cμ − λ) = 0.642857 / (20 − 15) = 0.1285714 s = 128.6 ms
    theory_ms = 128.6
    measured_ms = mean_wait_ms(arrival_rps=15, servers=2)
    _report(request, "M/M/c (λ=15, μ=10, c=2)", measured_ms, theory_ms)
    assert measured_ms == pytest.approx(theory_ms, rel=0.05)


def mean_wait_ms(arrival_rps: float, servers: int) -> float:
    """Mean time a request waits for a free slot, averaged over REPLICATIONS independent runs.

    Each run gets its own seed, so its arrivals and its work times are unrelated to every other run's.
    The average of the per-run means (rather than of every wait pooled together) weighs each run
    equally, which is what the standard deviation in this module's docstring was measured against.
    """
    return statistics.fmean(
        statistics.fmean(_waits_ms(arrival_rps, servers, seed)) for seed in range(1, REPLICATIONS + 1)
    )


def _waits_ms(arrival_rps: float, servers: int, seed: int) -> list[float]:
    """Every queue time recorded at the service in one run, after warmup.

    A request still waiting when the clock stops has no span yet and so is not counted; at these
    loads that is two or three requests out of several thousand.
    """
    work = random.Random(seed * 7919).expovariate  # its own stream: independent of the arrivals
    mean_work_ms = 1000 / MU_PER_S
    config = RunConfig(duration_s=DURATION_S, seed=seed, warmup_s=WARMUP_S)
    run = execute(_design(arrival_rps, servers), config, {"svc": lambda: work(1 / mean_work_ms)})
    return [
        span.queue_ms
        for req in run.metrics.requests
        if req.created_at >= WARMUP_S * 1000
        for span in req.spans
        if span.node_id == "svc"
    ]


def _design(arrival_rps: float, servers: int) -> Design:
    """Users → one service with `servers` slots behind a single line.

    One replica, not `servers` replicas: replicas each have their own queue, which would be `servers`
    separate M/M/1 queues. M/M/c is one line feeding every server, which is what concurrency within a
    replica is. The queue limit is the maximum, so nothing is ever turned away, and the client timeout
    is long enough that no request gives up; both would bias the waits that theory expects to see.
    """
    return Design.model_validate(
        {
            "name": "queueing theory",
            "version": 1,
            "nodes": [
                {
                    "id": "users",
                    "kind": "users",
                    "label": "Users",
                    "position": {"x": 0, "y": 0},
                    "params": {
                        "traffic": {"type": "constant", "rps": arrival_rps},
                        "clientTimeoutMs": 600_000,
                    },
                },
                {
                    "id": "svc",
                    "kind": "service",
                    "label": "Service",
                    "position": {"x": 0, "y": 0},
                    "params": {
                        "replicas": 1,
                        "concurrencyPerReplica": servers,
                        "queueLimit": 10_000,
                        "work": {"p50Ms": 100, "p99Ms": 100},  # replaced by the exponential sampler
                        "costPerReplicaMonth": 0,
                    },
                },
            ],
            "edges": [{"id": "e", "source": "users", "target": "svc"}],
        }
    )


def _report(request, case: str, measured_ms: float, theory_ms: float) -> None:
    """Print simulated vs theoretical (§18 asks for it), straight to the terminal past pytest's capture."""
    error = 100 * (measured_ms - theory_ms) / theory_ms
    request.config.get_terminal_writer().line(
        f"\n  {case}: simulated {measured_ms:.1f} ms vs theory {theory_ms:.1f} ms ({error:+.2f}%)"
        f" over {REPLICATIONS} runs of {DURATION_S} s"
    )
