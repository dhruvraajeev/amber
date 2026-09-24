"""Seeded streams and distributions (plan §8.2, §8.3): reproducible everywhere, and shaped as specified."""

import hashlib
import os
import random
import statistics
import subprocess
import sys

import pytest

from amber.sim.rng import lognormal_from_p50_p1, lognormal_from_percentiles, poisson, stream

N = 200_000


def draws(rng: random.Random, n: int = 5) -> list[float]:
    return [rng.random() for _ in range(n)]


def percentiles(samples: list[float]) -> list[float]:
    """The 1st..99th percentiles; index 0 is p1, 49 is p50, 98 is p99."""
    return statistics.quantiles(samples, n=100)


# ── Streams ──────────────────────────────────────────────────────────────────


def test_stream_seed_is_the_sha256_formula():
    digest = hashlib.sha256(b"42:n_api:work").digest()
    expected = random.Random(int.from_bytes(digest[:8], "big"))
    assert draws(stream(42, "n_api", "work")) == draws(expected)


def test_same_inputs_give_the_same_numbers():
    assert draws(stream(7, "n_db", "hit")) == draws(stream(7, "n_db", "hit"))


@pytest.mark.parametrize("other", [(8, "n_db", "hit"), (7, "n_api", "hit"), (7, "n_db", "work")])
def test_seed_node_and_purpose_each_pick_a_different_stream(other):
    assert draws(stream(7, "n_db", "hit")) != draws(stream(*other))


def test_unknown_purpose_is_refused():
    with pytest.raises(ValueError, match="unknown rng purpose"):
        stream(1, "n_api", "arrival")  # typo for "arrivals"


def test_streams_match_across_processes_with_different_hash_salts():
    # hash() is salted per process via PYTHONHASHSEED. Two children with different salts must print
    # exactly what this process computes; a hash()-based seed would differ.
    code = (
        "from amber.sim.rng import stream\nprint([stream(42, 'n_api', p).random() for p in ('work', 'hit')])"
    )
    expected = str([stream(42, "n_api", p).random() for p in ("work", "hit")])
    for salt in ("0", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": salt}
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == expected


# ── Distributions ────────────────────────────────────────────────────────────


def test_lognormal_recovers_p50_and_p99():
    mu, sigma = lognormal_from_percentiles(20, 80)  # a latency: median 20 ms, p99 80 ms
    rng = stream(1, "n_svc", "work")
    q = percentiles([rng.lognormvariate(mu, sigma) for _ in range(N)])
    assert q[49] == pytest.approx(20, rel=0.03)
    assert q[98] == pytest.approx(80, rel=0.03)


def test_lognormal_with_p99_equal_to_p50_never_varies():
    mu, sigma = lognormal_from_percentiles(15, 15)
    rng = stream(1, "n_svc", "work")
    assert sigma == 0
    assert [rng.lognormvariate(mu, sigma) for _ in range(100)] == pytest.approx([15] * 100)


@pytest.mark.parametrize(("p50", "p99"), [(0, 10), (-5, 10), (20, 10)])
def test_lognormal_refuses_impossible_percentiles(p50, p99):
    with pytest.raises(ValueError):
        lognormal_from_percentiles(p50, p99)


def test_tokens_per_second_lognormal_recovers_p50_and_the_slow_p1():
    mu, sigma = lognormal_from_p50_p1(60, 25)  # median 60 tok/s; 1% of calls slower than 25 tok/s
    rng = stream(1, "n_llm", "tokens")
    q = percentiles([rng.lognormvariate(mu, sigma) for _ in range(N)])
    assert q[49] == pytest.approx(60, rel=0.03)
    assert q[0] == pytest.approx(25, rel=0.03)


def test_tokens_per_second_refuses_a_p1_above_the_median():
    with pytest.raises(ValueError):
        lognormal_from_p50_p1(20, 30)


def test_poisson_has_the_right_mean_and_variance():
    rng = stream(3, "n_agent", "work")
    counts = [poisson(rng, 3.5) for _ in range(N)]
    # Standard error of the mean is sqrt(3.5 / 200k) ≈ 0.004; of the variance ≈ 0.012. Poisson: var == mean.
    assert statistics.fmean(counts) == pytest.approx(3.5, abs=0.02)
    assert statistics.pvariance(counts) == pytest.approx(3.5, abs=0.06)


def test_agent_with_mean_one_always_makes_exactly_one_llm_call():
    rng = stream(3, "n_agent", "work")
    assert {1 + poisson(rng, 0) for _ in range(1000)} == {1}
