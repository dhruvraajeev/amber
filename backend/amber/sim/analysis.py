"""Why a run looked the way it did (plan §8.9): where slow requests spend their time, and what to fix."""

import statistics
from collections import defaultdict
from collections.abc import Iterable

from amber.contracts import AttributionRow, Bottleneck, GpuSeries, NodeSummary, Summary, TimelinePoint
from amber.sim.request import Request

MAX_FINDINGS = 5
SEVERITIES = ("critical", "warn", "info")  # most severe first
# §8.9's table, row by row: name -> (severity, message). A finding ranks by its severity, then by its row.
# "kv_rejects" is §8.9's reject row worded for a self-hosted LLM, which has no queueLimit.
RULES = {
    "capacity": ("critical", "{name} is at {util}% capacity. Requests queue for up to {queue} waiting."),
    "queue_growing": ("critical", "{name}'s queue keeps growing. The system can't keep up at this traffic."),
    "rejects": ("critical", "{name} rejected {n} requests ({pct}%). Raise queueLimit or add capacity."),
    "kv_rejects": (
        "critical",
        "{name} turned away {n} requests ({pct}%) too big for its KV cache. "
        "Use a bigger GPU or a smaller output reserve.",
    ),
    "rate_limit": ("warn", "{name} hit its rate limit {n} times. Add retries/backoff or a higher tier."),
    "kv_full": (
        "critical",
        "{name} GPU memory is full {pct}% of the time. Requests wait for KV cache space.",
    ),
    "attribution": ("info", "{share}% of slow-request time is spent {doing} {name}."),
    "headroom": ("warn", "{name} is at {util}%. There's little headroom for spikes."),
}
ROW = {name: row for row, name in enumerate(RULES)}


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
    gpu_ids = {series.node_id for series in gpu}  # the self-hosted LLMs

    def add(rule: str, node_id: str, **values: object) -> None:
        severity, message = RULES[rule]
        finding = Bottleneck(
            severity=severity, node_id=node_id, message=message.format(name=labels[node_id], **values)
        )
        found.append((ROW[rule], finding))

    for n in nodes:
        if n.util_avg >= 0.9:
            add("capacity", n.id, util=_pct(n.util_avg), queue=round(n.queue_max))
        elif n.util_avg >= 0.7:
            add("headroom", n.id, util=_pct(n.util_avg))
        if _queue_growing([p.nodes[n.id].queue for p in timeline]):
            add("queue_growing", n.id)
        if n.rejects:
            pct = f"{100 * n.rejects / max(1, summary.requests):.1f}"
            if n.id in gpu_ids:  # a self-hosted LLM's rejects are calls too big for its KV cache
                add("kv_rejects", n.id, n=n.rejects, pct=pct)
            elif n.kind == "llm":  # a hosted LLM's rejects are 429s
                add("rate_limit", n.id, n=n.rejects)
            else:
                add("rejects", n.id, n=n.rejects, pct=pct)

    for series in gpu:
        full = sum(p.kv_pct >= 0.95 for p in series.points) / max(1, len(series.points))
        if full > 0.2:
            add("kv_full", series.node_id, pct=_pct(full))

    if rows and rows[0].queue_share + rows[0].work_share >= 0.5:
        top = rows[0]
        if top.queue_share >= top.work_share:
            add("attribution", top.node_id, share=_pct(top.queue_share), doing="waiting in")
        else:
            add("attribution", top.node_id, share=_pct(top.work_share), doing="working in")

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
