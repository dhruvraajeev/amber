"""The token bucket both rate limits share: the hosted LLM's (ms) and the API's per-client one (s)."""

import pytest

from amber.token_bucket import TokenBucket


def test_it_spends_what_it_starts_with_then_says_how_long_until_the_next_permit():
    bucket = TokenBucket(capacity=10, rate=2.0, permits=2)  # 2 permits a unit of time
    assert [bucket.take(0) for _ in range(2)] == [0, 0]
    assert bucket.take(0) == pytest.approx(0.5)  # empty: one permit is half a unit away
    assert bucket.take(0.25) == pytest.approx(0.25)  # a refusal spends nothing
    assert bucket.take(0.5) == 0


def test_it_refills_up_to_its_capacity_and_no_further():
    bucket = TokenBucket(capacity=3, rate=1.0, permits=0)
    assert bucket.take(1000) == 0
    assert [bucket.take(1000) for _ in range(3)] == [0, 0, pytest.approx(1.0)]  # 3 saved, not 1000


def test_it_never_starts_above_capacity_and_refuses_settings_that_could_never_grant():
    assert TokenBucket(capacity=2, rate=1.0, permits=50).permits == 2
    with pytest.raises(ValueError):
        TokenBucket(capacity=0.5, rate=1.0, permits=0)
    with pytest.raises(ValueError):
        TokenBucket(capacity=5, rate=0, permits=5)
