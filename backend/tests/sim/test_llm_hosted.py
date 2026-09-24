"""The hosted LLM node (plan §8.6): latency shape, first token, cost, and the rate limit with backoff."""

import statistics

import pytest
from test_nodes import NODE, fixed, send, send_at, statuses, trail

from amber.sim.kernel import Environment, Process
from amber.sim.nodes.llm_hosted import HostedLlm
from amber.sim.request import Request

# hosted-small-paid in shared/presets/hosted_llms.json: 512 prompt and 256 output tokens by default.
PROMPT, OUTPUT = 512, 256
USD_IN, USD_OUT = 0.15, 0.6


def llm(env, rpm=3000, retries=2, ttft_ms=400.0, tps=(64.0, 64.0), seed=42, node_id="llm"):
    """A hosted LLM node. The defaults are fixed: every call takes 400 ms + 256 / 64 s = 4400 ms.
    `ttft_ms=None` samples ttft instead (p50 400, p99 1500)."""
    params = {
        "mode": "hosted",
        "preset_id": "hosted-small-paid",
        "ttft": fixed(ttft_ms) if ttft_ms else {"p50_ms": 400.0, "p99_ms": 1500.0},
        "tokens_per_second": {"p50": tps[0], "p99_low": tps[1]},
        "input_usd_per_1m": USD_IN,
        "output_usd_per_1m": USD_OUT,
        "rate_limit_rpm": rpm,
        "max_retries": retries,
    }
    node = NODE.validate_python(
        {"id": node_id, "kind": "llm", "label": node_id, "position": {"x": 0, "y": 0}, "params": params}
    )
    return HostedLlm(env, node, seed)


def usd(calls, prompt=PROMPT, output=OUTPUT):
    return calls * (prompt * USD_IN + output * USD_OUT) / 1e6


def test_a_call_is_ttft_then_generation_and_costs_its_llm_tokens():
    env = Environment()
    node = llm(env)
    [req] = send(env, node, 1)
    assert req.status == "ok"
    assert trail(req) == [("llm", 0.0, 4400.0)]  # 400 ttft + 256 tokens at 64/s
    assert req.first_token_at == pytest.approx(400.0)
    assert node.usd == pytest.approx(usd(1))
    assert node.rejects == 0


def test_only_the_first_call_sets_first_token_and_explicit_sizes_are_billed():
    env = Environment()
    node = llm(env)
    req = Request("r", 0.0, float("inf"))

    def agent_like():  # two calls in a row, the way Step 20's agent will make them
        yield from node.call(req, 1000, 64)
        yield from node.call(req, 2000, 128)

    Process(env, agent_like())
    env.run(until=1e6)
    assert req.first_token_at == pytest.approx(400.0)
    assert trail(req) == [("llm", 0.0, 1400.0), ("llm", 0.0, 2400.0)]
    assert node.usd == pytest.approx(usd(1, 1000, 64) + usd(1, 2000, 128))


def test_tokens_per_second_has_its_slow_tail_at_p99_low():
    # Generation time is output / tps, so the fastest 1% of speeds is the fastest 1% of times and
    # the slow p99Low speed shows up as the p99 time. Checks the lognormal is fitted the right way up.
    env = Environment()
    node = llm(env, rpm=1e9, ttft_ms=1.0, tps=(60.0, 20.0))
    reqs = send(env, node, 50_000)
    gen_ms = sorted(req.spans[0].work_ms - 1.0 for req in reqs)
    q = statistics.quantiles(gen_ms, n=100)
    assert q[49] == pytest.approx(OUTPUT / 60 * 1000, rel=0.03)
    assert q[98] == pytest.approx(OUTPUT / 20 * 1000, rel=0.03)


def test_a_burst_over_the_limit_is_rate_limited_and_never_billed():
    env = Environment()
    node = llm(env, rpm=2, retries=0)
    reqs = send(env, node, 5)
    assert statuses(reqs) == ["ok", "ok", "rate_limited", "rate_limited", "rate_limited"]
    assert [len(r.spans) for r in reqs] == [1, 1, 0, 0, 0]  # a refused call leaves no span
    assert node.usd == pytest.approx(usd(2))
    assert node.rejects == 3


def test_the_bucket_refills_over_time_but_never_past_its_capacity():
    # 60 rpm: one permit per second, 60 at most. Everything at one instant runs in creation order.
    at_ms = [0.0] * 61 + [1000.0] * 2 + [600_000.0] * 61
    env = Environment()
    reqs = send_at(env, llm(env, rpm=60, retries=0), at_ms)
    limited = [r.created_at for r in reqs if r.status == "rate_limited"]
    # t=0: 60 permits, one call too many. t=1 s: one permit back. After 10 idle minutes: 60, not 600.
    assert limited == [0.0, 1000.0, 600_000.0]


def test_backoff_doubles_from_500_ms_up_to_8_s_plus_jitter():
    node = llm(Environment())
    for attempt, base in enumerate([500, 1000, 2000, 4000, 8000, 8000, 8000]):
        assert base <= node.backoff_ms(attempt) < base + 500


def test_jitter_varies_and_is_the_same_for_the_same_seed():
    a, b, c = llm(Environment()), llm(Environment()), llm(Environment(), seed=7)
    waits = [a.backoff_ms(0) for _ in range(20)]
    assert len(set(waits)) == 20
    assert waits == [b.backoff_ms(0) for _ in range(20)]
    assert waits != [c.backoff_ms(0) for _ in range(20)]


def test_a_throttled_call_retries_until_a_permit_frees_up():
    # 2 rpm: one permit every 30 s. The third call at t=0 waits 500+1000+2000+4000+8000+8000 ms
    # (23.5 s, plus ≤3 s of jitter) and is still refused; the 7th retry, at ≥31.5 s, gets through.
    env = Environment()
    node = llm(env, rpm=2, retries=7)
    reqs = send(env, node, 3)
    assert statuses(reqs) == ["ok", "ok", "ok"]
    backoff_ms = reqs[2].spans[0].queue_ms
    assert 31_500 <= backoff_ms < 31_500 + 7 * 500
    assert node.rejects == 7
    assert reqs[2].end == pytest.approx(backoff_ms + 4400.0)
    assert node.usd == pytest.approx(usd(3))


def test_running_out_of_retries_fails_the_request_after_the_backoff():
    env = Environment()
    node = llm(env, rpm=2, retries=3)
    reqs = send(env, node, 3)
    assert reqs[2].status == "rate_limited"
    assert 3_500 <= reqs[2].end < 3_500 + 3 * 500  # 500 + 1000 + 2000, each plus jitter
    assert node.rejects == 4  # the first try and three retries
    assert reqs[2].first_token_at is None


def test_retries_draw_jitter_from_their_own_stream_so_latencies_do_not_shift():
    # Same seed, varied ttft: the third call's latency must not depend on whether it was throttled
    # first, because its 7 jitter draws come from the "retry" stream, not the "work" one.
    def third_call_work_ms(rpm):
        env = Environment()
        return send(env, llm(env, rpm=rpm, retries=7, ttft_ms=None), 3)[2].spans[0].work_ms

    assert third_call_work_ms(rpm=2) == third_call_work_ms(rpm=3000)
