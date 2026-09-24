"""The service node: replicas of worker slots that hold a slot for the whole request (plan §8.5)."""

from amber.contracts import ServiceNode
from amber.sim.kernel import Environment, ProcessGen, Resource, Timeout
from amber.sim.nodes import Node
from amber.sim.request import Request, Span
from amber.sim.rng import lognormal_from_percentiles, stream


class Service(Node):
    """`replicas` × `concurrencyPerReplica` worker slots, each replica with its own waiting line.

    Thread-per-request: a request keeps its slot while it does its own work *and* while it waits on
    every downstream call, in edge order. So a slow database makes the service look busy too, which
    is how thread pools behave. Replicas are picked round robin, even when the chosen one is full and
    another has room, as with a round-robin proxy in front of independent replicas.
    """

    def __init__(self, env: Environment, node: ServiceNode, seed: int) -> None:
        super().__init__(env, node.id)
        p = node.params
        self.replicas = [Resource(env, p.concurrency_per_replica, p.queue_limit) for _ in range(p.replicas)]
        self._work = lognormal_from_percentiles(p.work.p50_ms, p.work.p99_ms)
        self._rng = stream(seed, node.id, "work")
        self._next = 0  # round-robin cursor over replicas

    def handle(self, req: Request) -> ProcessGen:
        replica = self.replicas[self._next]
        self._next = (self._next + 1) % len(self.replicas)

        grant = replica.request()
        if grant is None:  # the replica's line is full: 503
            req.status = "rejected"
            return
        queued_at = self.env.now
        yield grant  # outside the try: a slot is released only once it has been granted
        try:
            queue_ms = self.env.now - queued_at
            work_ms = self._rng.lognormvariate(*self._work)
            yield Timeout(self.env, work_ms)
            req.spans.append(Span(self.id, queue_ms, work_ms))
            for target in self.downstream:
                yield from target.handle(req)
                if req.failed:  # skip the remaining calls; the finally still frees the slot
                    return
        finally:
            replica.release()
