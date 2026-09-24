"""One simulated request and the trail of spans it leaves as it moves through the design (plan §8.5)."""

from dataclasses import dataclass, field
from typing import Literal, NamedTuple

# "ok" and "timeout" are decided at the end by the users node; the rest are errors raised on the way.
Status = Literal["ok", "timeout", "rejected", "rate_limited"]


class Span(NamedTuple):
    """Time one request spent at one node: waiting for a slot, then doing that node's own work.

    `work_ms` excludes downstream calls, which leave spans of their own. Step 15 sums these per node to
    find where slow requests spend their time.
    """

    node_id: str
    queue_ms: float
    work_ms: float


@dataclass(slots=True)
class Request:
    """A request's lifecycle. `status` stays None while it is in flight and nothing has gone wrong.

    Errors are statuses, not exceptions: a node that fails a request sets `status`, and every caller
    checks `failed` after a downstream call, stops its remaining calls, releases what it holds and
    returns. Only the first error is ever set, because nothing runs for the request after it.
    """

    id: str
    created_at: float  # ms
    deadline: float  # ms: created_at + the users node's clientTimeoutMs
    status: Status | None = None
    first_token_at: float | None = None  # ms; set by the first LLM call (Step 14)
    end: float | None = None  # ms
    spans: list[Span] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        """True once an error has been set while the request is still in flight."""
        return self.status is not None

    def finish(self, now: float) -> None:
        """Close the request at `now`. An error stays; otherwise it is "ok", or "timeout" if too late.

        A timed-out request still did all its work: the client gave up, the servers didn't know.
        """
        self.end = now
        if self.status is None:
            self.status = "timeout" if now > self.deadline else "ok"
