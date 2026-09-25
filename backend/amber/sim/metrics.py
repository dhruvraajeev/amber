"""What happened during a run, in 1-second buckets (plan §8.8).

Two kinds of data go into a bucket:
- Per request, sorted in after the run: an arrival counts in the bucket where the request was created;
  its outcome (status, latency) counts in the bucket where it happened (`outcome`).
- Per node, sampled live: a small process wakes at the end of every bucket and reads each node's
  counters (`Node.resources`, `served`, `rejects`), keeping what changed since the last bucket. It
  also takes one GPU snapshot per self-hosted LLM node (`RunResult.gpu`, §7.4).

Utilization is `busy slot-ms / (slots × bucket ms)`, straight from the kernel's integral. It is never
clamped: a value above 1 would mean a modelling bug, and hiding it would hide the bug.

The summary describes one set of requests: those that arrived after the first `warmupS` seconds (the
system starts empty, which flatters it), each counted once with its own outcome, as a benchmark counts
the requests it sends. So `requests` = completed + errors + timeouts + those still running at the end.
A request still running when the run stops is a timeout if its client's deadline had already passed:
its client gave up then, whatever the servers do later. Only one whose client is still waiting has no
outcome yet. The timeline keeps every second, warmup included, and counts each outcome in the second
it happened.

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
    GpuSeries,
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
from amber.sim.nodes.llm_selfhosted import SelfHostedLlm
from amber.sim.nodes.users import Users
from amber.sim.request import Request, Status

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


class Outcome(NamedTuple):
    """How one request turned out, as far as the run can tell."""

    status: Status
    at_ms: float  # when it happened: the request's end, or its client's deadline
    latency_ms: float | None  # end − created, for a request that got a response (late or not)


def outcome(req: Request, run_end_ms: float) -> Outcome | None:
    """The request's outcome by `run_end_ms`, or None while its client is still waiting.

    A request that ended in time has its own status. One still running (or ending only after the run)
    whose deadline passed before the run ended is a timeout at that deadline: it will end even later,
    so `Request.finish` could only say timeout too. It has no latency, since no response ever came
    within the run; its span trail is also incomplete, which keeps it out of attribution.
    """
    if req.end is not None and req.end < run_end_ms:
        latency = req.end - req.created_at if req.status in ANSWERED else None
        return Outcome(req.status, req.end, latency)
    if req.deadline < run_end_ms:
        return Outcome("timeout", req.deadline, None)
    return None


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
        self._gpu = {
            nid: GpuSeries(node_id=nid, points=[]) for nid, n in nodes.items() if isinstance(n, SelfHostedLlm)
        }
        Process(env, self._sample())

    def _sample(self) -> ProcessGen:
        """At the end of each bucket, store what every node's counters did during it, and snapshot
        every GPU at that instant (its point's `t` is that end, in seconds)."""
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
            for node_id, series in self._gpu.items():
                series.points.append(self.nodes[node_id].gpu_point(self.env.now / 1000))

    def gpu_series(self) -> list[GpuSeries]:
        """One series per self-hosted LLM node, in design order, one point per simulated second."""
        return list(self._gpu.values())

    @cached_property
    def requests(self) -> list[Request]:
        """Every request the users nodes created. Read after the run."""
        return [r for node in self.nodes.values() if isinstance(node, Users) for r in node.requests]

    @cached_property
    def outcomes(self) -> list[tuple[Request, Outcome | None]]:
        """Every request with its outcome at the end of the run. Read after the run."""
        return [(req, outcome(req, self._duration_ms)) for req in self.requests]

    @cached_property
    def buckets(self) -> list[Bucket]:
        """Every bucket, with each request's arrival and outcome sorted in. Read after the run."""
        for req, out in self.outcomes:
            self._buckets[int(req.created_at // BUCKET_MS)].arrivals += 1
            if out is None:
                continue
            bucket = self._buckets[int(out.at_ms // BUCKET_MS)]
            bucket.ends[out.status] += 1
            if out.latency_ms is not None:
                bucket.latencies.append(out.latency_ms)
        return self._buckets

    @property
    def measured(self) -> list[Bucket]:
        """The buckets after warmup; all of them if warmup covers the whole run."""
        return [b for b in self.buckets if b.t >= self._warmup_s] or self.buckets

    @cached_property
    def measured_outcomes(self) -> list[tuple[Request, Outcome | None]]:
        """The requests the summary describes, those that arrived after warmup, with their outcomes."""
        start_ms = self.measured[0].t * 1000
        return [(req, out) for req, out in self.outcomes if req.created_at >= start_ms]

    def answered(self) -> list[Request]:
        """Measured requests that got a response, late or not: what latency and attribution look at."""
        return [req for req, out in self.measured_outcomes if out is not None and out.latency_ms is not None]

    def summary(self) -> Summary:
        outcomes = [out for _, out in self.measured_outcomes if out is not None]
        ends = Counter(out.status for out in outcomes)
        latencies = [out.latency_ms for out in outcomes if out.latency_ms is not None]
        ttfts = [r.first_token_at - r.created_at for r in self.answered() if r.first_token_at is not None]
        return Summary(
            requests=len(self.measured_outcomes),
            completed=ends["ok"],
            errors=sum(ends[s] for s in ERRORS),
            timeouts=ends["timeout"],
            rejected=ends["rejected"],
            throughput_rps=ends["ok"] / _seconds(self.measured),
            error_rate=_error_rate(ends),
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
        return TimelinePoint(
            t=group[0].t,
            arrivals_rps=sum(b.arrivals for b in group) / seconds,
            throughput_rps=ends["ok"] / seconds,
            error_rate=_error_rate(ends),
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


def _error_rate(ends: Counter[str]) -> float:
    """The share of outcomes that weren't "ok"; 0 when nothing had an outcome."""
    total = ends.total()
    return (total - ends["ok"]) / total if total else 0.0


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
