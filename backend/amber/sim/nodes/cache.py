"""The cache node: a lookup, then either an answer or a trip down the miss path (plan §8.5)."""

from amber.contracts import CacheNode
from amber.sim.kernel import Environment, ProcessGen, Timeout
from amber.sim.nodes import Node
from amber.sim.request import Request, Span
from amber.sim.rng import lognormal_from_percentiles, stream


class Cache(Node):
    """Every request pays the lookup `latency`; a hit (probability `hitRate`) returns right there,
    a miss continues to the single downstream node. No capacity limit: caches are rarely the queue.
    """

    def __init__(self, env: Environment, node: CacheNode, seed: int) -> None:
        super().__init__(env, node.id)
        p = node.params
        self._hit_rate = p.hit_rate
        self._latency = lognormal_from_percentiles(p.latency.p50_ms, p.latency.p99_ms)
        self._work_rng = stream(seed, node.id, "work")
        self._hit_rng = stream(seed, node.id, "hit")

    def handle(self, req: Request) -> ProcessGen:
        latency_ms = self._work_rng.lognormvariate(*self._latency)
        yield Timeout(self.env, latency_ms)
        req.spans.append(Span(self.id, 0.0, latency_ms))
        if self._hit_rng.random() < self._hit_rate:
            return
        yield from self.downstream[0].handle(req)
