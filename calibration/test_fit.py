"""fit.py recovers known coefficients from rows built with them.

Run: cd backend && uv run pytest ../calibration
"""

import pytest
from fit import fit

A_P, B_P, A_D, B_D, C_V, DRAFT_MS, N = 20.0, 0.5, 12.0, 1.5, 0.05, 3.0, 128


def row(run: str, c: int, prompt: int, k: int = 0) -> dict:
    step = A_D + B_D * c
    if run == "draft":
        step = DRAFT_MS
    draft_n = accepted = 0
    if run == "speculative":
        draft_n, accepted = 32 * k, 20 * k  # 32 steps of k draft tokens each
        step = (k * DRAFT_MS + (A_D + B_D) * (1 + C_V * k)) * 32 / N  # per output token
    return {"run": run, "draft_tokens": k, "concurrency": c, "prompt_tokens": prompt, "prompt_n": prompt,
            "prompt_ms": A_P + B_P * prompt, "predicted_n": N, "predicted_ms": step * N,
            "draft_n": draft_n, "draft_n_accepted": accepted}  # fmt: skip


def test_fit_recovers_the_coefficients() -> None:
    rows = [row("base", c, p) for c in (1, 2, 4, 8) for p in (128, 512, 2048)]
    rows += [row("draft", 1, 128)] + [row("speculative", 1, 128, k) for k in (2, 4, 8)]
    # Overlapped prefill makes long-prompt decode slower; the fit must ignore those rows.
    rows += [row("base", 8, 2048) | {"predicted_ms": 1e6}]
    got = fit(rows)
    assert (got["prefillBaseMs"], got["prefillMsPerToken"]) == pytest.approx((A_P, B_P))
    assert (got["decodeBaseMs"], got["decodeMsPerSequence"]) == pytest.approx((A_D, B_D))
    assert got["verifyCostPerDraftToken"] == pytest.approx(C_V)
    assert got["speculative"] == {"draftStepMs": DRAFT_MS, "acceptanceRate": 0.625}
    assert got["fit"]["decode"] == {"r2": 1.0, "samples": 4}


def test_negative_coefficients_are_refused() -> None:
    rows = [row("base", 1, p) | {"prompt_ms": 100 - 0.01 * p} for p in (128, 512, 2048)]
    with pytest.raises(SystemExit, match="negative"):
        fit(rows + [row("base", c, 128) for c in (2, 4)])


def test_an_overstated_draft_cost_floors_c_v_at_zero() -> None:
    rows = [row("base", c, 128) for c in (1, 2, 4, 8)] + [row("base", 1, p) for p in (512, 2048)]
    rows += [row("draft", 1, 128) | {"predicted_ms": 2 * DRAFT_MS * N}]
    rows += [row("speculative", 1, 128, k) for k in (2, 4, 8)]
    assert fit(rows)["verifyCostPerDraftToken"] == 0


def test_a_negative_fixed_cost_becomes_zero() -> None:
    # Cost exactly proportional to the work, plus noise that tips the intercept below 0.
    rows = [row("base", 1, p) | {"prompt_ms": 2.8 * p + 5 * (p == 2048)} for p in (128, 512, 2048)]
    got = fit(rows + [row("base", c, 128) for c in (2, 4)])
    assert got["prefillBaseMs"] == 0 and got["prefillMsPerToken"] == pytest.approx(2.8, rel=0.01)
