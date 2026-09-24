"""When requests arrive: the three traffic profiles as a random arrival stream (plan §8.4).

Arrivals are an open-loop, non-homogeneous Poisson process: the rate follows the profile over time,
and users keep arriving whether or not the system keeps up. `rate`, `peak` and `expected_requests`
mirror frontend/src/lib/estimate.ts and validate.ts, so the UI and the backend agree on limits.
"""

import random
from collections.abc import Iterator

from amber.contracts import ConstantTraffic, SpikeTraffic, TrafficProfile


def rate(traffic: TrafficProfile, t_s: float, duration_s: float) -> float:
    """Arrival rate (req/s) at second `t_s` of a run lasting `duration_s`."""
    if isinstance(traffic, ConstantTraffic):
        return traffic.rps
    if isinstance(traffic, SpikeTraffic):
        in_peak = traffic.peak_start_s <= t_s < traffic.peak_start_s + traffic.peak_duration_s
        return traffic.peak_rps if in_peak else traffic.base_rps
    return traffic.start_rps + (traffic.end_rps - traffic.start_rps) * t_s / duration_s


def peak(traffic: TrafficProfile) -> float:
    """The highest rate the profile ever reaches (req/s)."""
    if isinstance(traffic, ConstantTraffic):
        return traffic.rps
    if isinstance(traffic, SpikeTraffic):
        return max(traffic.base_rps, traffic.peak_rps)
    return max(traffic.start_rps, traffic.end_rps)


def expected_requests(traffic: TrafficProfile, duration_s: float) -> float:
    """Requests the profile sends over the run: the exact area under the rate curve (§3)."""
    if isinstance(traffic, ConstantTraffic):
        return traffic.rps * duration_s  # rectangle
    if isinstance(traffic, SpikeTraffic):
        # Base rectangle over the whole run, plus the extra rate for the part of the peak window
        # inside the run (the peak may start after the run ends, or outlast it).
        peak_end = min(traffic.peak_start_s + traffic.peak_duration_s, duration_s)
        peak_s = max(0.0, peak_end - traffic.peak_start_s)
        return traffic.base_rps * duration_s + (traffic.peak_rps - traffic.base_rps) * peak_s
    return (traffic.start_rps + traffic.end_rps) / 2 * duration_s  # trapezoid: average height


def arrival_times_ms(traffic: TrafficProfile, duration_s: float, rng: random.Random) -> Iterator[float]:
    """Arrival times in milliseconds (the kernel's clock), increasing, all before the run ends.

    Thinning (Lewis–Shedler): draw candidates from a constant-rate Poisson process at the profile's
    peak rate, then keep each one with probability `rate(t) / peak`. What survives is a Poisson process
    whose rate follows the profile exactly. `rng` should be the users node's "arrivals" stream.
    """
    max_rps = peak(traffic)
    if max_rps <= 0:
        return
    t_s = 0.0
    while True:
        t_s += rng.expovariate(max_rps)  # gap between candidates at the peak rate
        if t_s >= duration_s:
            return
        if rng.random() * max_rps < rate(traffic, t_s, duration_s):
            yield t_s * 1000
