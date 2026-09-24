"""Slow-request attribution and the bottleneck rules (plan §8.9): one scenario per rule, then ranking."""

import pytest
from test_metrics import config, design_with
from test_nodes import service, users

from amber.contracts import (
    AttributionRow,
    GpuPoint,
    GpuSeries,
    LatencySummary,
    NodePoint,
    NodeSummary,
    Summary,
    TimelinePoint,
)
from amber.sim.analysis import attribution, bottlenecks
from amber.sim.kernel import Environment
from amber.sim.metrics import Metrics
from amber.sim.request import Request, Span

LABELS = {"api": "API", "db": "Postgres", "llm": "Hosted LLM", "gpu": "Llama on L4"}


def node(node_id="api", kind="service", util=0.0, queue_max=0.0, rejects=0):
    return NodeSummary(
        id=node_id, kind=kind, util_avg=util, util_max=util, queue_avg=0, queue_max=queue_max,
        rejects=rejects, monthly_usd=0,
    )  # fmt: skip


def summary(requests=1000, p99=250.0):
    return Summary(
        requests=requests, completed=requests, errors=0, timeouts=0, rejected=0, throughput_rps=10,
        error_rate=0, latency_ms=LatencySummary(p50=50, p95=150, p99=p99, max=400),
    )  # fmt: skip


def timeline(queues):
    """A timeline whose points carry these queue lengths per node id, one point per list entry."""
    n = len(next(iter(queues.values())))
    return [
        TimelinePoint(
            t=i, arrivals_rps=0, throughput_rps=0, error_rate=0, p50=0, p95=0, p99=0,
            nodes={k: NodePoint(util=0, queue=q[i], rejects=0, throughput_rps=0) for k, q in queues.items()},
        )
        for i in range(n)
    ]  # fmt: skip


def run(nodes=(), queues=None, gpu=(), rows=(), s=None, points=None):
    """The findings for these fixtures, as (severity, node id, message). Queues default to empty."""
    points = points or timeline(queues or {n.id: [0.0] * 10 for n in nodes} or {"api": [0.0] * 10})
    found = bottlenecks(LABELS, s or summary(), list(nodes), points, list(gpu), list(rows))
    return [(b.severity, b.node_id, b.message) for b in found]


def row(node_id, queue, work):
    return AttributionRow(node_id=node_id, queue_share=queue, work_share=work)


# ── Attribution ──────────────────────────────────────────────────────────────


def slow(created, end, *spans):
    r = Request(f"r{created}", created, created + 10_000, status="ok", end=end)
    r.spans = [Span(*s) for s in spans]
    return r


def test_attribution_pools_the_slowest_requests_span_time_and_splits_waiting_from_working():
    reqs = [
        slow(0, 100, ("api", 10, 20), ("db", 50, 20)),  # 100 ms: at the threshold, counted
        slow(0, 300, ("api", 0, 30), ("db", 200, 70)),  # 300 ms: counted
        slow(0, 40, ("api", 0, 40)),  # 40 ms: below p99, ignored
    ]
    rows = attribution(reqs, p99=100)
    total = 10 + 20 + 50 + 20 + 30 + 200 + 70  # 400 ms across both slow requests
    assert rows == [row("db", 250 / total, 90 / total), row("api", 10 / total, 50 / total)]
    assert sum(r.queue_share + r.work_share for r in rows) == pytest.approx(1)


def test_no_slow_time_means_no_attribution():
    assert attribution([], p99=100) == []
    assert attribution([slow(0, 200, ("lb", 0, 0))], p99=100) == []


# ── One scenario per rule ────────────────────────────────────────────────────


def test_capacity_at_90_percent_is_critical_and_silences_the_70_percent_warning():
    assert run([node(util=0.94, queue_max=37.6)]) == [
        ("critical", "api", "API is at 94% capacity. Requests queue for up to 38 waiting.")
    ]


def test_capacity_at_70_percent_warns_about_headroom():
    assert run([node(util=0.72)]) == [("warn", "api", "API is at 72%. There's little headroom for spikes.")]


def test_a_queue_that_keeps_growing_is_critical_but_a_full_steady_one_is_not():
    growing = [0.0] * 30 + [float(i) for i in range(30)]  # overload starts halfway through the run
    assert run([node()], {"api": growing}) == [
        ("critical", "api", "API's queue keeps growing. The system can't keep up at this traffic.")
    ]
    assert run([node()], {"api": [200.0] * 60}) == run([node()])  # full and flat: rejects say it instead


def test_rejects_are_critical_with_their_share_of_requests():
    assert run([node(rejects=50)]) == [
        ("critical", "api", "API rejected 50 requests (5.0%). Raise queueLimit or add capacity.")
    ]


def test_a_hosted_llm_reject_is_a_rate_limit_hit_and_a_warning():
    assert run([node("llm", kind="llm", rejects=12)]) == [
        ("warn", "llm", "Hosted LLM hit its rate limit 12 times. Add retries/backoff or a higher tier.")
    ]


def test_a_self_hosted_llm_reject_is_not_called_a_rate_limit():
    """Its rejects are calls too big for the GPU's KV cache: the plain reject rule, never the 429 one."""
    gpu = GpuSeries(node_id="gpu", points=[GpuPoint(t=1, kv_pct=0.1, batch=1, waiting=0)])
    assert run([node("gpu", kind="llm", rejects=4)], gpu=[gpu]) == [
        ("critical", "gpu", "Llama on L4 rejected 4 requests (0.4%). Raise queueLimit or add capacity.")
    ]


def test_gpu_memory_full_more_than_a_fifth_of_the_time_is_critical():
    def series(full_points):
        kv = [0.99] * full_points + [0.5] * (10 - full_points)
        return GpuSeries(
            node_id="gpu", points=[GpuPoint(t=i, kv_pct=k, batch=1, waiting=0) for i, k in enumerate(kv)]
        )

    assert run(gpu=[series(3)]) == [
        (
            "critical",
            "gpu",
            "Llama on L4 GPU memory is full 30% of the time. Requests wait for KV cache space.",
        )
    ]
    assert run(gpu=[series(2)]) == run()  # exactly 20% is not more than 20%


def test_one_node_holding_half_the_slow_time_is_named_with_what_it_was_doing():
    assert run(rows=[row("db", 0.45, 0.15), row("api", 0.1, 0.3)]) == [
        ("info", "db", "45% of slow-request time is spent waiting in Postgres.")
    ]
    assert run(rows=[row("api", 0.1, 0.5)]) == [
        ("info", "api", "50% of slow-request time is spent working in API.")
    ]
    assert run(rows=[row("db", 0.3, 0.19)]) == run()  # 49%: nothing dominates


def test_nothing_triggered_reports_the_p99():
    assert run(s=summary(p99=212.4)) == [("info", None, "No bottlenecks at this traffic. p99 is 212 ms.")]


# ── Ranking ──────────────────────────────────────────────────────────────────


def test_findings_rank_by_severity_then_table_order_then_design_order_and_stop_at_five():
    nodes = [
        node("api", util=0.75),  # warn: headroom
        node("db", util=0.95, rejects=5),  # critical: capacity, rejects
        node("llm", kind="llm", rejects=3),  # warn: rate limit
        node("gpu", util=0.92),  # critical: capacity
    ]
    found = run(nodes, rows=[row("db", 0.6, 0.1)])  # info: attribution
    assert [(sev, nid) for sev, nid, _ in found] == [
        ("critical", "db"),  # capacity rows first, in design order
        ("critical", "gpu"),
        ("critical", "db"),  # then the rejects row
        ("warn", "llm"),  # rate limit comes before headroom in the table
        ("warn", "api"),
    ]  # the info finding is sixth, past the cap


# ── End to end ───────────────────────────────────────────────────────────────


def test_an_overloaded_service_is_diagnosed_from_a_real_run():
    env = Environment()
    source, api = users(env, rps=200), service(env, "api", concurrency=1, queue=20, work_ms=10.0)
    source.downstream = [api]  # 200 rps offered to a slot that serves 100 rps
    metrics = Metrics(env, {"users": source, "api": api}, config(30, warmup_s=5))
    source.start(30)
    env.run(30_000)

    points = metrics.timeline()
    assert all(p.nodes["api"].util <= 1 + 1e-9 for p in points)  # never clamped, and never needs to be
    s = metrics.summary()
    [_, api] = metrics.node_summaries(design_with("users", "api"), {})
    rows = attribution(metrics.answered(), s.latency_ms.p99)
    found = run([api], rows=rows, s=s, points=points)
    assert [(sev, nid) for sev, nid, _ in found] == [
        ("critical", "api"),
        ("critical", "api"),
        ("info", "api"),
    ]
    assert "capacity" in found[0][2] and "rejected" in found[1][2] and "waiting in API" in found[2][2]
