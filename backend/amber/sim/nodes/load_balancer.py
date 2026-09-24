"""The load balancer: a small overhead, then one downstream target per request (plan §8.5)."""

from collections import Counter

from amber.contracts import LoadBalancerNode
from amber.sim.kernel import Environment, ProcessGen, Timeout
from amber.sim.nodes import Node
from amber.sim.request import Request, Span
from amber.sim.rng import lognormal_from_percentiles, stream


class LoadBalancer(Node):
    """Picks a target by round robin, or by fewest requests in flight (`leastConnections`).

    It counts in-flight requests itself, per target, as a real load balancer does: it only knows
    what it has sent and not yet seen come back. Least-connections ties go round robin, so at low
    load it spreads traffic evenly instead of piling onto the first target.
    """

    def __init__(self, env: Environment, node: LoadBalancerNode, seed: int) -> None:
        super().__init__(env, node.id)
        p = node.params
        self._least = p.algorithm == "leastConnections"
        self._overhead = lognormal_from_percentiles(p.overhead.p50_ms, p.overhead.p99_ms)
        self._rng = stream(seed, node.id, "work")
        self._next = 0  # round-robin cursor
        self.in_flight: Counter[int] = Counter()  # downstream index -> requests sent, not yet back

    def handle(self, req: Request) -> ProcessGen:
        overhead_ms = self._rng.lognormvariate(*self._overhead)
        yield Timeout(self.env, overhead_ms)
        req.spans.append(Span(self.id, 0.0, overhead_ms))

        target = self._pick()
        self.in_flight[target] += 1
        try:
            yield from self.downstream[target].handle(req)
        finally:
            self.in_flight[target] -= 1

    def _pick(self) -> int:
        n = len(self.downstream)
        target = self._next
        if self._least:  # scan from the cursor, so the first of several equally idle targets wins
            target = min(((self._next + k) % n for k in range(n)), key=self.in_flight.__getitem__)
        self._next = (target + 1) % n
        return target
