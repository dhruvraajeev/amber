"""validate.py's two pieces of arithmetic: the benchmark's throughput, and the replay through Amber's
scheduler against the timing model worked out by hand.

Run: cd backend && uv run pytest ../calibration
"""

from validate import HELD_OUT, benchmark_design, replay, throughput_rps

from amber.presets import profiles
from amber.sim.nodes import llm_selfhosted


def test_throughput_counts_each_round_until_its_slowest_request() -> None:
    cell = [{"rep": rep, "e2e_ms": ms} for rep, ms in ((0, 100), (0, 200), (1, 300), (1, 50))]
    assert throughput_rps(cell) == 4 / 0.5  # 4 requests over 200 + 300 ms


def test_replay_matches_the_timing_model() -> None:
    profile = profiles()["default"] | {
        "gpuPresetId": "nvidia-l4-24gb",
        "modelPresetId": "llama-3.1-8b-instruct-fp16",
    }
    llm_selfhosted.PROFILES[HELD_OUT] = llm_selfhosted.TimingProfile(10, 1, 5, 2)
    design = benchmark_design(profile, prompt=100, output=4, rps=1, k=0, spec=None)
    # Both calls prefill together (10 + 200 tokens), then 3 decode steps at batch 2 (5 + 2·2 each).
    got = replay(design, c=2, prompt=100, output=4)
    assert got == {"ttftP50": 210, "ttftP99": 210, "e2eP50": 237, "e2eP99": 237}
