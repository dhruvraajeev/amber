"""The API's guardrails (plan §3): body size, per-IP rate limit, simulations at once, wall time.

The design-level limits (nodes, edges, duration, traffic, estimated requests) are not here: they are
graph-validation issues in `sim/graph.py`, so the UI shows them on the canvas like any other rule.
"""

import json

from fastapi import Request

from amber.api.errors import ApiError
from amber.token_bucket import TokenBucket

MAX_BODY_BYTES = 256 * 1024
SIMULATIONS_PER_MINUTE = 30  # per client IP
MAX_CONCURRENT_SIMULATIONS = 2  # the simulator is CPU-bound; more would just share the same cores
MAX_WALL_S = 20.0  # real seconds one simulation may take before it is stopped (504)


class RateLimiter:
    """A token bucket per client: `per_minute` permits, refilled continuously, starting full, so a new
    visitor can run a burst of simulations straight away.

    In memory, so it covers one container only. At more than one replica it needs a shared store
    (Redis, or a Mongo TTL collection) or the ingress to do the limiting.
    """

    def __init__(self, per_minute: int):
        self.capacity = per_minute
        self.per_second = per_minute / 60
        self._buckets: dict[str, TokenBucket] = {}

    def take(self, client: str, now: float) -> float:
        """Take one permit for `client` at time `now` (seconds). Returns 0 if it got one, else the
        seconds until one is free, for the 429's `Retry-After`."""
        bucket = self._buckets.get(client)
        if bucket is None:
            bucket = self._buckets[client] = TokenBucket(self.capacity, self.per_second, self.capacity, now)
        if wait_s := bucket.take(now):
            return wait_s
        if len(self._buckets) > 10_000:
            self._forget_idle(now)
        return 0.0

    def _forget_idle(self, now: float) -> None:
        """Drop clients whose bucket has refilled: forgetting them changes nothing, and it keeps a
        stream of new addresses from growing the dict forever."""
        full_after = self.capacity / self.per_second
        self._buckets = {c: b for c, b in self._buckets.items() if now - b.at < full_after}


async def read_json(request: Request) -> object:
    """The request body as JSON, refusing more than 256 KB without reading the rest of it."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _too_large()
    body = bytearray()
    async for chunk in request.stream():  # a chunked body has no content-length, so count as it comes
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise _too_large()
    try:
        return json.loads(body)
    except ValueError as e:  # also covers bytes that aren't UTF-8
        raise ApiError(400, "bad_json", f"The request body isn't valid JSON: {e}.") from None


def _too_large() -> ApiError:
    return ApiError(413, "too_large", f"Request bodies are limited to {MAX_BODY_BYTES // 1024} KB.")
