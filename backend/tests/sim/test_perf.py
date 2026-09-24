"""The simulator has to be fast enough to feel interactive (plan §8.12).

A run happens while someone waits for it, so the targets are: the classic template at 200 rps for
60 s (about 12,000 requests) in under 2 s, and the 200,000-request cap in under 15 s. The bounds
asserted here are those targets — already about ten times the measured time on a laptop — so a slower
CI runner still passes and a real performance regression still fails. Both are marked `slow` and left
out of CI (`pytest -m "not slow"`), because a timing assertion on a shared runner is a coin toss.
"""

import time

import pytest
from test_run import config, design, template

from amber.contracts import Design, RunConfig
from amber.sim.run import simulate

REQUEST_CAP = 200_000  # §3's limit on one run


def timed(design_, config_) -> tuple[float, int]:
    started_at = time.perf_counter()
    result = simulate(design_, config_)
    return time.perf_counter() - started_at, result.engine.simulated_requests


@pytest.mark.slow
def test_the_classic_template_at_200_rps_for_a_minute_is_interactive(request):
    seconds, requests = timed(design("classic-web-app"), config(duration_s=60))
    _report(request, f"classic-web-app, 60 s at 200 rps: {requests} requests in {seconds:.2f} s")
    assert requests == pytest.approx(12_000, rel=0.05)
    assert seconds < 2


@pytest.mark.slow
def test_the_largest_run_the_limits_allow_finishes(request):
    """333 rps for the full 600 s: just under the 200,000-request cap `sim/graph.validate` enforces."""
    raw = template("classic-web-app")
    next(n for n in raw["nodes"] if n["kind"] == "users")["params"]["traffic"]["rps"] = 333
    seconds, requests = timed(Design.model_validate(raw), RunConfig(duration_s=600, seed=1))
    _report(request, f"classic-web-app, 600 s at 333 rps: {requests} requests in {seconds:.2f} s")
    assert requests == pytest.approx(REQUEST_CAP, rel=0.05)
    assert seconds < 15


def _report(request, line: str) -> None:
    request.config.get_terminal_writer().line(f"\n  {line}")
