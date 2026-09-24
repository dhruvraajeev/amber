"""Seeded random streams and the distributions the simulator samples from (plan §8.2, §8.3).

Determinism rule: the same design, config and seed must give a byte-identical result on any machine,
in any process. So every random number comes from a `random.Random` stream whose seed is derived with
SHA-256 from `(seed, node_id, purpose)`. Never Python's built-in `hash()`: it is salted per process.

Each node draws from separate streams per purpose, so adding a draw in one place (say, cache hits)
doesn't shift the numbers used everywhere else (say, work times).
"""

import hashlib
import math
import random

PURPOSES = frozenset({"arrivals", "work", "hit", "tokens", "accept"})

# z-score of the 99th percentile of the standard normal: P(Z <= 2.3263479) = 0.99.
Z99 = 2.3263479


def stream(seed: int, node_id: str, purpose: str) -> random.Random:
    """The random stream one node uses for one purpose. Same inputs, same numbers, in any process."""
    if purpose not in PURPOSES:
        raise ValueError(f"unknown rng purpose {purpose!r}; expected one of {sorted(PURPOSES)}")
    digest = hashlib.sha256(f"{seed}:{node_id}:{purpose}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def lognormal_from_percentiles(p50: float, p99: float) -> tuple[float, float]:
    """The `(mu, sigma)` of the lognormal whose median is `p50` and 99th percentile is `p99`.

    A lognormal is `exp(normal(mu, sigma))`. Taking logs turns it back into a normal, whose median
    is `mu` and whose 99th percentile is `mu + Z99 * sigma`. So `mu = ln(p50)` and
    `sigma = (ln(p99) - ln(p50)) / Z99`. When `p99 == p50`, sigma is 0 and every sample is p50.

    Callers compute this once per node and draw each sample with `rng.lognormvariate(mu, sigma)`.
    """
    if not 0 < p50 <= p99:
        raise ValueError("needs 0 < p50 <= p99")
    return math.log(p50), (math.log(p99) - math.log(p50)) / Z99


def lognormal_from_p50_p1(p50: float, p1: float) -> tuple[float, float]:
    """The `(mu, sigma)` of a lognormal whose median is `p50` and whose *1st* percentile is `p1`.

    Hosted LLM tokens-per-second (§8.3): the risk is a slow tail, so the given bound is the low one
    (`tokensPerSecond.p99Low`, the speed 99% of calls beat). Mirror image of the p99 case.
    """
    if not 0 < p1 <= p50:
        raise ValueError("needs 0 < p1 <= p50")
    return math.log(p50), (math.log(p50) - math.log(p1)) / Z99


def poisson(rng: random.Random, mean: float) -> int:
    """A Poisson-distributed count, by Knuth's method (multiply uniforms until below e^-mean).

    Agent LLM calls per request are `1 + poisson(rng, llmCallsMean - 1)` (§8.5).
    """
    # ponytail: Knuth is O(mean) per draw and e^-mean underflows near mean 745. Agent means are
    # single or double digits; switch to a normal approximation if large means ever matter.
    if mean < 0:
        raise ValueError("mean must be >= 0")
    limit, k, product = math.exp(-mean), 0, rng.random()
    while product > limit:
        k += 1
        product *= rng.random()
    return k
