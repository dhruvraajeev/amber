"""The database node: a connection pool with a waiting line in front of it (plan §8.5)."""

from amber.contracts import DatabaseNode
from amber.sim.kernel import Environment, ProcessGen, Resource, Timeout
from amber.sim.nodes import Node
from amber.sim.request import Request, Span
from amber.sim.rng import lognormal_from_percentiles, stream


class Database(Node):
    """`connectionPool` queries run at once; up to `queueLimit` more wait; beyond that, rejected.
    A leaf: it never calls anything downstream.
    """

    def __init__(self, env: Environment, node: DatabaseNode, seed: int) -> None:
        super().__init__(env, node.id)
        p = node.params
        self.pool = Resource(env, p.connection_pool, p.queue_limit)
        self._query = lognormal_from_percentiles(p.query.p50_ms, p.query.p99_ms)
        self._rng = stream(seed, node.id, "work")

    def handle(self, req: Request) -> ProcessGen:
        grant = self.pool.request()
        if grant is None:  # pool busy and the line is full
            req.status = "rejected"
            return
        queued_at = self.env.now
        yield grant  # outside the try: a connection is released only once it has been granted
        try:
            queue_ms = self.env.now - queued_at
            query_ms = self._rng.lognormvariate(*self._query)
            yield Timeout(self.env, query_ms)
            req.spans.append(Span(self.id, queue_ms, query_ms))
        finally:
            self.pool.release()
