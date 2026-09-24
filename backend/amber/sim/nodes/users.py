"""The users node: where requests come from, and where each one's final status is decided (plan §8.5)."""

from amber.contracts import UsersNode
from amber.sim.arrivals import arrival_times_ms
from amber.sim.kernel import Environment, Process, ProcessGen, Timeout
from amber.sim.nodes import Node
from amber.sim.request import Request
from amber.sim.rng import stream


class Users(Node):
    """Sends requests to its single downstream node on the traffic profile's schedule.

    Arrivals are open-loop: new requests keep coming whether or not earlier ones have finished.
    Every request it creates is kept in `requests`, which is what metrics read after the run.
    Nothing ever calls into a users node (§7.6 USERS_EDGES), so it has no `handle`.
    """

    def __init__(self, env: Environment, node: UsersNode, seed: int) -> None:
        super().__init__(env, node.id)
        self._params = node.params
        self._rng = stream(seed, node.id, "arrivals")
        self.requests: list[Request] = []

    def start(self, duration_s: float) -> None:
        """Begin sending requests for the first `duration_s` seconds of the run."""
        Process(self.env, self._arrive(duration_s))

    def _arrive(self, duration_s: float) -> ProcessGen:
        timeout_ms = self._params.client_timeout_ms
        for at_ms in arrival_times_ms(self._params.traffic, duration_s, self._rng):
            # Clamp: the clock can land a rounding error past `at_ms` when two arrivals nearly coincide.
            yield Timeout(self.env, max(0.0, at_ms - self.env.now))
            now = self.env.now
            req = Request(f"{self.id}#{len(self.requests)}", now, now + timeout_ms)
            self.requests.append(req)
            Process(self.env, self._serve(req))

    def _serve(self, req: Request) -> ProcessGen:
        yield from self.downstream[0].handle(req)
        req.finish(self.env.now)
