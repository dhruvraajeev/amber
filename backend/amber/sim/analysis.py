"""Why a run looked the way it did (plan §8.9): where slow requests spend their time, and what to fix."""

import statistics
from collections import defaultdict
from collections.abc import Iterable

from amber.contracts import AttributionRow, Bottleneck, GpuSeries, NodeSummary, Summary, TimelinePoint
from amber.sim.request import Request

MAX_FINDINGS = 5
SEVERITIES = ("critical", "warn", "info")  # most severe first
# §8.9's table, row by row: (severity, message). A finding ranks by its severity, then by its row.
RULES = (
    ("critical", "{name} is at {util}% capacity. Requests queue for up to {queue} waiting."),
    ("critical", "{name}'s queue keeps growing. The system can't keep up at this traffic."),
    ("critical", "{name} rejected {n} requests ({pct}%). Raise queueLimit or add capacity."),
    ("warn", "{name} hit its rate limit {n} times. Add retries/backoff or a higher tier."),
    ("critical", "{name} GPU memory is full {pct}% of the time. Requests wait for KV cache space."),
    ("info", "{share}% of slow-request time is spent {doing} {name}."),
    ("warn", "{name} is at {util}%. There's little headroom for spikes."),
)


def attribution(answered: Iterable[Request], p99: float) -> list[AttributionRow]:
    """Where requests at or above `p99` spent their time, per node, split into waiting and working.

    Every slow request's span time is pooled, then each node's share is taken of the total, so all rows'
    queue and work shares add up to 1. Largest share first; ties keep the order nodes were first seen.
    """
    queue_ms: defaultdict[str, float] = defaultdict(float)
    work_ms: defaultdict[str, float] = defaultdict(float)
    for req in answered:
        if req.end - req.created_at >= p99:
            for span in req.spans:
                queue_ms[span.node_id] += span.queue_ms
                work_ms[span.node_id] += span.work_ms
    total = sum(queue_ms.values()) + sum(work_ms.values())
    if not total:
        return []
    rows = [
        AttributionRow(
            node_id=node_id, queue_share=queue_ms[node_id] / total, work_share=work_ms[node_id] / total
        )
        for node_id in queue_ms
        if queue_ms[node_id] + work_ms[node_id] > 0
    ]
    return sorted(rows, key=lambda r: r.queue_share + r.work_share, reverse=True)


def bottlenecks(
    labels: dict[str, str],
    summary: Summary,
    nodes: list[NodeSummary],
    timeline: list[TimelinePoint],
    gpu: list[GpuSeries],
    rows: list[AttributionRow],
) -> list[Bottleneck]:
    """§8.9's rules in plain English with numbers, naming nodes by `labels` (node id -> label): most
    severe first, at most 5.

    Within a severity, findings keep the table's rule order, then design order. Each rule speaks at most
    once per node, and the 70% headroom warning stays quiet when the 90% capacity rule already fired.
    """
    found: list[tuple[int, Bottleneck]] = []  # (row in RULES, finding)
    gpu_ids = {series.node_id for series in gpu}  # self-hosted LLMs, whose rejects are calls too big for KV

    def add(rule: int, node_id: str, **values: object) -> None:
        severity, message = RULES[rule]
        finding = Bottleneck(
            severity=severity, node_id=node_id, message=message.format(name=labels[node_id], **values)
        )
        found.append((rule, finding))

    for n in nodes:
        if n.util_avg >= 0.9:
            add(0, n.id, util=_pct(n.util_avg), queue=round(n.queue_max))
        elif n.util_avg >= 0.7:
            add(6, n.id, util=_pct(n.util_avg))
        if _queue_growing([p.nodes[n.id].queue for p in timeline]):
            add(1, n.id)
        if n.rejects and n.kind == "llm" and n.id not in gpu_ids:  # a hosted LLM's rejects are 429s
            add(3, n.id, n=n.rejects)
        elif n.rejects:
            add(2, n.id, n=n.rejects, pct=f"{100 * n.rejects / max(1, summary.requests):.1f}")

    for series in gpu:
        full = sum(p.kv_pct >= 0.95 for p in series.points) / max(1, len(series.points))
        if full > 0.2:
            add(4, series.node_id, pct=_pct(full))

    if rows and rows[0].queue_share + rows[0].work_share >= 0.5:
        top = rows[0]
        if top.queue_share >= top.work_share:
            add(5, top.node_id, share=_pct(top.queue_share), doing="waiting in")
        else:
            add(5, top.node_id, share=_pct(top.work_share), doing="working in")

    if not found:
        p99 = round(summary.latency_ms.p99)
        return [Bottleneck(severity="info", message=f"No bottlenecks at this traffic. p99 is {p99} ms.")]
    found.sort(key=lambda f: (SEVERITIES.index(f[1].severity), f[0]))  # stable: design order within a row
    return [finding for _, finding in found[:MAX_FINDINGS]]


def _queue_growing(queue: list[float]) -> bool:
    """§8.9: over the last half of the run the queue trends up (least-squares slope > 0), and it ends at
    more than twice its median length over the whole run."""
    last_half = queue[len(queue) // 2 :]
    if len(last_half) < 2:
        return False
    slope = statistics.linear_regression(range(len(last_half)), last_half).slope
    return slope > 0 and queue[-1] > 2 * statistics.median(queue)


def _pct(fraction: float) -> int:
    return round(100 * fraction)
