"""A token bucket: permits that refill continuously up to a cap, one spent per use.

Two places use it: the hosted LLM node's rate limit (plan §8.6, time in simulated milliseconds) and the
API's per-client limit on simulations (§3, time in real seconds). The bucket doesn't care which unit;
`rate` and `now` just have to agree.
"""


class TokenBucket:
    """Holds up to `capacity` permits, gaining `rate` per unit of time, starting with `permits`."""

    __slots__ = ("capacity", "rate", "permits", "at")

    def __init__(self, capacity: float, rate: float, permits: float, at: float = 0.0) -> None:
        if capacity < 1 or rate <= 0:
            raise ValueError("a bucket needs capacity >= 1 and rate > 0, or it could never grant a permit")
        self.capacity = capacity
        self.rate = rate
        self.permits = min(permits, capacity)
        self.at = at  # when `permits` was last brought up to date

    def take(self, now: float) -> float:
        """Spend one permit at `now` and return 0, or, if none is left, spend nothing and return how long
        until one will be. So `if bucket.take(now):` reads "if I have to wait"."""
        self.permits = min(self.capacity, self.permits + (now - self.at) * self.rate)
        self.at = now
        if self.permits < 1:
            return (1 - self.permits) / self.rate
        self.permits -= 1
        return 0.0
