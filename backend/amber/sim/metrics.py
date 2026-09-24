"""What happened during a run, in 1-second buckets (plan §8.8).

Two kinds of data go into a bucket:
- Per request, sorted in after the run: an arrival counts in the bucket where the request was created;
  its outcome (status, latency) counts in the bucket where it ended.
- Per node, sampled live: a small process wakes at the end of every bucket and reads each node's
  counters (`Node.resources`, `served`, `rejects`), keeping what changed since the last bucket.

Utilization is `busy slot-ms / (slots × bucket ms)`, straight from the kernel's integral. It is never
clamped: a value above 1 would mean a modelling bug, and hiding it would hide the bug.

The summary describes one set of requests: those that arrived after the first `warmupS` seconds (the
system starts empty, which flatters it), each counted once with its own outcome, as a benchmark counts
the requests it sends. So `requests` = completed + errors + timeouts + those still running at the end.
The timeline keeps every second, warmup included, and counts each outcome in the second it happened.

A timeline over 300 buckets is merged in pairs. Merging keeps the raw counts and latencies, so a merged
point is exact: its rates are totals over its whole width, and its percentiles come from all of its
latencies, not from combining each bucket's percentiles.
"""

import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property
from typing import NamedTuple

from amber.contracts import (
    Design,
    LatencySummary,
    NodePoint,
    NodeSummary,
    Percentiles,
    RunConfig,
    Summary,
    TimelinePoint,
)
from amber.sim.kernel import Environment, Process, ProcessGen, Timeout
from amber.sim.nodes import Node
from amber.sim.nodes.users import Users
from amber.sim.request import Request

BUCKET_MS = 1000.0
MAX_POINTS = 300
ANSWERED = ("ok", "timeout")  # got a response, late or not; errors fail fast and would flatter latency
ERRORS = ("rejected", "rate_limited")


class NodeSample(NamedTuple):
    """One node over one bucket."""

    busy_slot_ms: float
    slot_ms: float  # slots × bucket width: what busy_slot_ms is out of; 0 with no capacity limit
    queue_peak: int
    rejects: int
    served: int


@dataclass(slots=True)
class Bucket:
    t: float  # seconds, bucket start
    width_ms: float  # BUCKET_MS, except a shorter last bucket when durationS isn't whole
    arrivals: int = 0
    ends: Counter[str] = field(default_factory=Counter)  # status -> requests that ended here
    latencies: list[float] = field(default_factory=list)  # ms, answered requests only
    nodes: dict[str, NodeSample] = field(default_factory=dict)


class Metrics:
    """Build it before `env.run` (it starts the sampler); read the results after."""

    def __init__(self, env: Environment, nodes: dict[str, Node], config: RunConfig) -> None:
        self.env = env
        self.nodes = nodes
        self._duration_ms = duration_ms = config.duration_s * 1000
        self._buckets = [
            Bucket(i * BUCKET_MS / 1000, min(BUCKET_MS, duration_ms - i * BUCKET_MS))
            for i in range(math.ceil(duration_ms / BUCKET_MS))
        ]
        self._warmup_s = config.warmup_s
        Process(env, self._sample())

    def _sample(self) -> ProcessGen:
        """At the end of each bucket, store what every node's counters did during it."""
        last = {node_id: (0.0, 0, 0) for node_id in self.nodes}  # busy slot-ms, rejects, served
        for bucket in self._buckets:
            yield Timeout(self.env, bucket.width_ms)
            for node_id, node in self.nodes.items():
                busy = sum(r.busy_slot_ms for r in node.resources)
                slots = sum(r.capacity for r in node.resources)
                # ponytail: a service's queue is the sum of each replica's peak, an upper bound on the
                # peak of their sum (exact for one replica). Track a node-wide line if that ever matters.
                queue_peak = sum(r.pop_queue_peak() for r in node.resources)
                was_busy, was_rejects, was_served = last[node_id]
                bucket.nodes[node_id] = NodeSample(
                    busy - was_busy,
                    slots * bucket.width_ms,
                    queue_peak,
                    node.rejects - was_rejects,
                    node.served - was_served,
                )
                last[node_id] = (busy, node.rejects, node.served)

    @cached_property
    def requests(self) -> list[Request]:
        """Every request the users nodes created. Read after the run."""
        return [r for node in self.nodes.values() if isinstance(node, Users) for r in node.requests]

    @cached_property
    def buckets(self) -> list[Bucket]:
        """Every bucket, with each request sorted in. Read after the run."""
        for req in self.requests:
            self._buckets[int(req.created_at // BUCKET_MS)].arrivals += 1
            # Still in flight when the run stopped (an arrival with no outcome), or ended after the
            # last bucket if the run was allowed past its duration.
            if req.end is None or req.end >= self._duration_ms:
                continue
            bucket = self._buckets[int(req.end // BUCKET_MS)]
            bucket.ends[req.status] += 1
            if req.status in ANSWERED:
                bucket.latencies.append(req.end - req.created_at)
        return self._buckets

    @property
    def measured(self) -> list[Bucket]:
        """The buckets after warmup; all of them if warmup covers the whole run."""
        return [b for b in self.buckets if b.t >= self._warmup_s] or self.buckets

    @cached_property
    def measured_requests(self) -> list[Request]:
        """The requests the summary describes: those that arrived after warmup. Read after the run."""
        start_ms = self.measured[0].t * 1000
        return [r for r in self.requests if r.created_at >= start_ms]

    @cached_property
    def finished(self) -> list[Request]:
        """Measured requests with an outcome; the rest were still running when the run stopped."""
        return [r for r in self.measured_requests if r.end is not None and r.end < self._duration_ms]

    def answered(self) -> list[Request]:
        """Finished requests that got a response, late or not: what latency and attribution look at."""
        return [r for r in self.finished if r.status in ANSWERED]

    def summary(self) -> Summary:
        ends = Counter(r.status for r in self.finished)
        answered = self.answered()
        latencies = [r.end - r.created_at for r in answered]
        ttfts = [r.first_token_at - r.created_at for r in answered if r.first_token_at is not None]
        finished = ends.total()
        return Summary(
            requests=len(self.measured_requests),
            completed=ends["ok"],
            errors=sum(ends[s] for s in ERRORS),
            timeouts=ends["timeout"],
            rejected=ends["rejected"],
            throughput_rps=ends["ok"] / _seconds(self.measured),
            error_rate=(finished - ends["ok"]) / finished if finished else 0.0,
            latency_ms=LatencySummary(**_percentiles(latencies), max=max(latencies, default=0.0)),
            ttft_ms=Percentiles(**_percentiles(ttfts)) if ttfts else None,
        )

    def timeline(self) -> list[TimelinePoint]:
        """One point per bucket, or per pair of buckets past 300 (durationS ≤ 600 keeps it to pairs)."""
        size = math.ceil(len(self.buckets) / MAX_POINTS)
        return [self._point(self.buckets[i : i + size]) for i in range(0, len(self.buckets), size)]

    def _point(self, group: list[Bucket]) -> TimelinePoint:
        seconds = _seconds(group)
        ends = sum((b.ends for b in group), Counter())
        finished = ends.total()
        return TimelinePoint(
            t=group[0].t,
            arrivals_rps=sum(b.arrivals for b in group) / seconds,
            throughput_rps=ends["ok"] / seconds,
            error_rate=(finished - ends["ok"]) / finished if finished else 0.0,
            **_percentiles([x for b in group for x in b.latencies]),
            nodes={nid: _node_point([b.nodes[nid] for b in group], seconds) for nid in self.nodes},
        )

    def node_summaries(self, design: Design, monthly_usd: dict[str, float]) -> list[NodeSummary]:
        """Each node over the measured buckets, in design order, with its share of the monthly cost."""
        measured = self.measured
        summaries = []
        for node in design.nodes:
            samples = [b.nodes[node.id] for b in measured]
            queues = [s.queue_peak for s in samples]
            summaries.append(
                NodeSummary(
                    id=node.id,
                    kind=node.kind,
                    util_avg=_util(samples),
                    util_max=max(_util([s]) for s in samples),
                    queue_avg=statistics.fmean(queues),
                    queue_max=max(queues),
                    rejects=sum(s.rejects for s in samples),
                    monthly_usd=monthly_usd.get(node.id, 0.0),
                )
            )
        return summaries


def _seconds(buckets: list[Bucket]) -> float:
    return sum(b.width_ms for b in buckets) / 1000


def _node_point(samples: list[NodeSample], seconds: float) -> NodePoint:
    return NodePoint(
        util=_util(samples),
        queue=max(s.queue_peak for s in samples),
        rejects=sum(s.rejects for s in samples),
        throughput_rps=sum(s.served for s in samples) / seconds,
    )


def _util(samples: list[NodeSample]) -> float:
    """Busy slot-ms over available slot-ms, so a merged window weighs each bucket by its width."""
    slot_ms = sum(s.slot_ms for s in samples)
    return sum(s.busy_slot_ms for s in samples) / slot_ms if slot_ms else 0.0


def _percentiles(values: list[float]) -> dict[str, float]:
    """p50/p95/p99 (inclusive method: interpolated between sorted values); zeros for an empty bucket."""
    if len(values) < 2:
        v = values[0] if values else 0.0
        return {"p50": v, "p95": v, "p99": v}
    cuts = statistics.quantiles(values, n=100, method="inclusive")
    return {"p50": cuts[49], "p95": cuts[94], "p99": cuts[98]}
