"""Bucketed metrics (plan §8.8): utilization from the busy-slot integral, warmup, and downsampling."""

import pytest
from test_nodes import send_at, service, users

from amber.contracts import Design, RunConfig
from amber.sim.kernel import Environment, Process, Resource, Timeout
from amber.sim.metrics import Metrics
from amber.sim.nodes import Node
from amber.sim.request import Request


def config(duration_s, warmup_s=0.0):
    return RunConfig(duration_s=duration_s, seed=1, warmup_s=warmup_s)


def req(created_ms, end_ms, status="ok", first_token_ms=None):
    r = Request(f"r{created_ms}", created_ms, created_ms + 5000, status=status, end=end_ms)
    r.first_token_at = first_token_ms
    return r


def with_requests(duration_s, reqs, warmup_s=0.0):
    """Metrics over a run with no traffic of its own, holding `reqs` as if a users node had sent them."""
    env = Environment()
    source = users(env, rps=1)
    source.requests.extend(reqs)
    metrics = Metrics(env, {"users": source}, config(duration_s, warmup_s))
    env.run(duration_s * 1000)
    return metrics


def test_utilization_is_busy_slot_ms_over_available_slot_ms_including_a_short_last_bucket():
    env = Environment()
    node = Node(env, "n")
    pool = Resource(env, capacity=2, queue_limit=0)
    node.resources = [pool]
    metrics = Metrics(env, {"n": node}, config(10.5))  # 11 buckets; the last is 500 ms wide

    def hold(start_ms, ms):
        yield Timeout(env, start_ms)
        yield pool.request()
        yield Timeout(env, ms)
        pool.release()

    Process(env, hold(0, 1500))  # one of two slots busy from 0 to 1.5 s
    Process(env, hold(9800, 600))  # 9.8 s to 10.4 s, across into the short last bucket
    env.run(10_500)

    util = [p.nodes["n"].util for p in metrics.timeline()]
    # Worked by hand: busy slot-ms / (2 slots × bucket ms).
    assert util == pytest.approx([1000 / 2000, 500 / 2000, 0, 0, 0, 0, 0, 0, 0, 200 / 2000, 400 / 1000])
    [n] = metrics.node_summaries(design_with("n"), {})
    assert n.util_avg == pytest.approx(2100 / (2 * 10_500))  # every bucket weighed by its width
    assert n.util_max == pytest.approx(0.5)


def test_queue_peak_rejects_and_throughput_per_bucket():
    env = Environment()
    svc = service(env, concurrency=1, queue=1, work_ms=400.0)
    metrics = Metrics(env, {"svc": svc}, config(10))
    send_at(env, svc, [0, 0, 0])  # one runs, one waits, one is turned away

    first, second = (p.nodes["svc"] for p in metrics.timeline()[:2])
    assert (first.queue, first.rejects, first.throughput_rps) == (1, 1, 2)  # served at 0.4 s and 0.8 s
    assert (second.queue, second.rejects, second.throughput_rps) == (0, 0, 0)


def test_warmup_is_left_out_of_the_summary_but_kept_in_the_timeline():
    reqs = [
        req(500, 700),  # all inside warmup
        req(1500, 2500),  # arrives during warmup, ends after: only its outcome counts
        req(2100, 2400, first_token_ms=2200),
        req(3000, 3500),
        req(3000, 9000, "timeout"),
        req(4000, 4001, "rejected"),
        req(5000, 5002, "rate_limited"),
        req(9500, None, None),  # still in flight at the end: an arrival, no outcome
    ]
    metrics = with_requests(10, reqs, warmup_s=2)

    s = metrics.summary()
    assert (s.requests, s.completed, s.timeouts, s.rejected, s.errors) == (6, 3, 1, 1, 2)
    assert s.error_rate == 3 / 6  # of the 6 that finished after warmup, 3 weren't ok
    assert s.throughput_rps == 3 / 8
    assert (s.latency_ms.p50, s.latency_ms.max) == (750, 6000)  # of 300, 500, 1000, 6000 ms
    assert (s.ttft_ms.p50, s.ttft_ms.p99) == (100, 100)
    assert sorted(r.created_at for r in metrics.answered()) == [1500, 2100, 3000, 3000]

    timeline = metrics.timeline()
    assert [p.t for p in timeline] == list(range(10))
    assert (timeline[0].arrivals_rps, timeline[0].throughput_rps, timeline[0].p50) == (1, 1, 200)
    assert (timeline[4].throughput_rps, timeline[4].error_rate) == (0, 1)  # a reject isn't throughput
    assert timeline[9].error_rate == 1  # the timeout ended in the last bucket


def test_no_llm_means_no_ttft_and_an_all_warmup_run_summarizes_everything():
    s = with_requests(10, [req(0, 100), req(9000, 9100)], warmup_s=60).summary()
    assert s.requests == 2 and s.ttft_ms is None


@pytest.mark.parametrize(
    ("duration_s", "points"), [(10, 10), (300, 300), (301, 151), (599.5, 300), (600, 300)]
)
def test_the_timeline_never_exceeds_300_points(duration_s, points):
    assert len(with_requests(duration_s, []).timeline()) == points


def test_a_merged_point_is_exact_over_both_buckets():
    # Bucket 0 has one 100 ms request; bucket 1 has 400 ms and 700 ms. Averaging the buckets' medians
    # would say 325 ms; the true median of the three is 400 ms.
    metrics = with_requests(600, [req(0, 100), req(1000, 1400), req(1100, 1800)])
    first = metrics.timeline()[0]
    assert (first.t, first.arrivals_rps, first.throughput_rps, first.p50) == (0, 1.5, 1.5, 400)


def test_sampled_utilization_adds_up_to_the_work_actually_done():
    env = Environment()
    source, svc = users(env, rps=50), service(env, concurrency=1, work_ms=10.0)
    source.downstream = [svc]
    metrics = Metrics(env, {"users": source, "svc": svc}, config(60))
    source.start(60)
    env.run(60_000)

    busy_ms = sum(p.nodes["svc"].util * 1000 for p in metrics.timeline())  # 1 slot, 1000 ms buckets
    assert busy_ms == pytest.approx(svc.served * 10.0, abs=10.0)  # the last request may still be running
    assert sum(p.nodes["svc"].throughput_rps for p in metrics.timeline()) == svc.served
    assert metrics.summary().requests == len(source.requests)


def design_with(*node_ids):
    """A design whose nodes carry these ids (their kind and params don't matter to metrics)."""
    nodes = [
        {"id": i, "kind": "cache", "label": i, "position": {"x": 0, "y": 0},
         "params": {"hitRate": 0, "latency": {"p50Ms": 1, "p99Ms": 1}, "costPerMonth": 0}}
        for i in node_ids
    ]  # fmt: skip
    return Design(name="t", version=1, nodes=nodes, edges=[])
