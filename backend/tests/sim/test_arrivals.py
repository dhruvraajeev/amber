"""Arrivals follow the traffic profile (plan §8.4): exact expected counts, sampled counts within 3σ."""

import math

import pytest

from amber.contracts import ConstantTraffic, RampTraffic, SpikeTraffic
from amber.sim.arrivals import arrival_times_ms, expected_requests, peak, rate
from amber.sim.rng import stream

SPIKE = SpikeTraffic(type="spike", base_rps=50, peak_rps=200, peak_start_s=20, peak_duration_s=10)
RAMP = RampTraffic(type="ramp", start_rps=0, end_rps=120)


def arrivals(traffic, duration_s, seed=42):
    return list(arrival_times_ms(traffic, duration_s, stream(seed, "users", "arrivals")))


def within_3_sigma(count, expected):
    """A Poisson count has variance equal to its mean, so σ = √mean."""
    assert abs(count - expected) <= 3 * math.sqrt(expected), f"{count} vs {expected}"


# ── expected_requests: exact, the same numbers estimate.ts gives ─────────────


def test_expected_requests_is_exact():
    assert expected_requests(ConstantTraffic(type="constant", rps=100), 60) == 6000
    assert expected_requests(SPIKE, 60) == 4500  # 50·60 + (200 − 50)·10
    assert expected_requests(RAMP, 60) == 3600  # (0 + 120) / 2 · 60


def test_expected_requests_clips_the_peak_window_to_the_run():
    assert expected_requests(SPIKE, 25) == 50 * 25 + 150 * 5  # peak cut off at the end of the run
    assert expected_requests(SPIKE, 15) == 50 * 15  # peak starts after the run ends


def test_rate_and_peak():
    assert [rate(SPIKE, t, 60) for t in (19.9, 20, 29.9, 30)] == [50, 200, 200, 50]  # window is [20, 30)
    assert rate(RAMP, 30, 60) == 60
    assert peak(SPIKE) == 200 and peak(RAMP) == 120
    assert peak(SpikeTraffic(type="spike", base_rps=80, peak_rps=10, peak_start_s=0, peak_duration_s=5)) == 80


# ── thinning: sampled counts match the profile ───────────────────────────────


def test_constant_count_within_3_sigma():
    within_3_sigma(len(arrivals(ConstantTraffic(type="constant", rps=100), 60)), 6000)


def test_ramp_count_within_3_sigma_in_each_half():
    """Thinning is what shapes the ramp: without it, every candidate at 120 req/s would be kept."""
    times = arrivals(RAMP, 60)
    first_half = sum(t < 30_000 for t in times)
    within_3_sigma(first_half, 900)  # 0 → 60 req/s over 30 s
    within_3_sigma(len(times) - first_half, 2700)  # 60 → 120 req/s over 30 s


def test_spike_counts_match_per_window():
    times = arrivals(SPIKE, 60)
    in_peak = sum(20_000 <= t < 30_000 for t in times)
    within_3_sigma(in_peak, 2000)  # 200 req/s for 10 s
    within_3_sigma(len(times) - in_peak, 2500)  # 50 req/s for the other 50 s


def test_times_are_increasing_milliseconds_inside_the_run():
    times = arrivals(SPIKE, 60)
    assert times == sorted(times)
    assert 0 < times[0] and times[-1] < 60_000


@pytest.mark.parametrize(
    "traffic", [ConstantTraffic(type="constant", rps=0), RampTraffic(type="ramp", start_rps=0, end_rps=0)]
)
def test_zero_traffic_sends_nothing(traffic):
    assert arrivals(traffic, 60) == []


def test_same_seed_same_arrivals_different_seed_different():
    assert arrivals(SPIKE, 60, seed=7) == arrivals(SPIKE, 60, seed=7)
    assert arrivals(SPIKE, 60, seed=7) != arrivals(SPIKE, 60, seed=8)
