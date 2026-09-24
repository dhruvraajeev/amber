"""The node kinds a design is built from (plan §8.5). Each one turns a request into simulated time."""

from amber.sim.kernel import Environment, ProcessGen, Resource
from amber.sim.request import Request, Span


class Node:
    """What every node shares: the clock, its id, the nodes it calls, and the counters metrics read.

    `downstream` is filled in after every node exists (Step 16 wires it from `design.edges`), since a
    node can't be handed targets that haven't been built yet.

    Metrics (Step 15) sample three things from every node, once per simulated second: `resources`
    (the slot pools behind utilization and queue length: kernel `Resource`s, or anything with the same
    `capacity`, `busy_slot_ms` and `pop_queue_peak()`, like a GPU replica; empty for kinds with no
    capacity limit),
    `served` (requests whose own work finished here) and `rejects` (requests turned away here).
    """

    def __init__(self, env: Environment, node_id: str) -> None:
        self.env = env
        self.id = node_id
        self.downstream: list[Node] = []
        self.resources: list[Resource] = []
        self.served = 0
        self.rejects = 0

    def record(self, req: Request, queue_ms: float, work_ms: float) -> None:
        """Log this node's span on `req` and count it as served here."""
        req.spans.append(Span(self.id, queue_ms, work_ms))
        self.served += 1

    def handle(self, req: Request) -> ProcessGen:
        """Serve `req`, calling downstream nodes with `yield from`, and return when it is done here.

        A node records its own span once its own work is done, so spans read in visit order. If it
        fails the request it sets `req.status` and returns; its caller sees `req.failed` and unwinds.
        """
        raise NotImplementedError
