"""The node kinds a design is built from (plan §8.5). Each one turns a request into simulated time."""

from amber.sim.kernel import Environment, ProcessGen
from amber.sim.request import Request


class Node:
    """What every node shares: the clock, its id, and the nodes it calls, in edge order.

    `downstream` is filled in after every node exists (Step 16 wires it from `design.edges`), since a
    node can't be handed targets that haven't been built yet.
    """

    def __init__(self, env: Environment, node_id: str) -> None:
        self.env = env
        self.id = node_id
        self.downstream: list[Node] = []

    def handle(self, req: Request) -> ProcessGen:
        """Serve `req`, calling downstream nodes with `yield from`, and return when it is done here.

        A node records its own span once its own work is done, so spans read in visit order. If it
        fails the request it sets `req.status` and returns; its caller sees `req.failed` and unwinds.
        """
        raise NotImplementedError
