"""Fit Amber's self-hosted LLM timing model to a llamacpp_bench.py run; write shared/profiles/<id>.json.

    python3 calibration/fit.py calibration/data/<run> --id <profile id> \\
        --gpu-preset <shared/presets/gpus.json id> --model-preset <shared/presets/models.json id>

Standard library only. The model (docs/simulation-model.md, "Self-hosted LLM") is three lines, and each
is fitted by least squares, with fixed costs held at 0 or above, from the rows where the server's own
timings measure exactly that quantity:

- prefill `a_p + b_p · tokens`: concurrency 1, where `prompt_ms` is one prompt's pass and nothing else.
- decode `a_d + b_d · batch`: 128-token prompts. All `c` of them fit in one prefill pass, so every step
  after it decodes exactly `c` sequences, and `predicted_ms / predicted_n` is one step at batch `c`.
  With longer prompts some slots start decoding while others still prefill, which this model doesn't
  describe; those rows are for checking the simulator against, not for fitting it.
- verify `c_v`, when the run has speculative rows: each step drafts `k` tokens with the draft model and
  then checks them, so `step = decode(1) + k · (draft_ms + decode(1) · c_v)`, a line in `k` whose slope
  holds `c_v`. Steps per request are `draft_n / k` (every step drafts exactly `k`); `draft_ms` is the
  draft model's own per-token time. That includes sampling and streaming, which a draft token inside a
  speculative step doesn't pay, so it runs high; a `c_v` pushed below 0 by it is floored at 0.
"""

import argparse
import csv
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECODE_PROMPT_TOKENS = 128


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run", type=Path, help="a calibration/data/<run> folder")
    p.add_argument("--id", required=True, help="the profile id (and file name) designs will use")
    p.add_argument("--gpu-preset", required=True, help="its shared/presets/gpus.json entry")
    p.add_argument("--model-preset", required=True, help="its shared/presets/models.json entry")
    args = p.parse_args()

    rows = load(args.run / "requests.csv")
    meta = json.loads((args.run / "meta.json").read_text())
    chip = meta["hardware"].split(",")[0]
    profile = {
        "id": args.id,
        "name": f"{meta['model'].removesuffix('.gguf')} on {chip} (measured {meta['date']})",
        **fit(rows),
        "hardware": meta["hardware"],
        "server": f"llama.cpp {meta['server']}",
        "modelId": meta["model"],
        "gpuPresetId": args.gpu_preset,
        "modelPresetId": args.model_preset,
        "measuredAt": meta["date"],
        "data": args.run.resolve().relative_to(ROOT).as_posix(),
    }
    out = ROOT / "shared" / "profiles" / f"{args.id}.json"
    out.write_text(json.dumps(profile, indent=2) + "\n")
    print(json.dumps({k: profile[k] for k in ("fit", "speculative") if k in profile}, indent=2))
    print(f"wrote {out.relative_to(ROOT)}")


def load(path: Path) -> list[dict]:
    """requests.csv as dicts of numbers (the `run` column stays text)."""
    with path.open() as f:
        return [{k: v if k == "run" else float(v) for k, v in row.items()} for row in csv.DictReader(f)]


def fit(rows: list[dict]) -> dict:
    """The profile's coefficients plus how well each line fits (R², sample count)."""
    base = [r for r in rows if r["run"] == "base"]
    solo = [r for r in base if r["concurrency"] == 1]
    a_p, b_p, prefill = line([r["prompt_n"] for r in solo], [r["prompt_ms"] for r in solo])
    batched = [r for r in base if r["prompt_tokens"] == DECODE_PROMPT_TOKENS]
    a_d, b_d, decode = line([r["concurrency"] for r in batched], [per_token(r) for r in batched])
    profile = {
        "prefillBaseMs": a_p,
        "prefillMsPerToken": b_p,
        "decodeBaseMs": a_d,
        "decodeMsPerSequence": b_d,
        "verifyCostPerDraftToken": 0.1,  # the model's default, kept when the run has no speculative rows
        "fit": {"prefill": prefill, "decode": decode},
    }
    spec = [r for r in rows if r["run"] == "speculative"]
    if spec:
        draft_ms = statistics.fmean(per_token(r) for r in rows if r["run"] == "draft")
        decode_1 = a_d + b_d
        step_base, per_draft_token, verify = line(
            [r["draft_tokens"] for r in spec], [step_ms(r) for r in spec]
        )
        c_v = (per_draft_token - draft_ms) / decode_1
        if c_v < 0:
            print(f"c_v fitted {c_v:.4f}: the draft model's solo time overstates its cost; using 0")
        profile["verifyCostPerDraftToken"] = max(c_v, 0.0)
        # The line's intercept is a plain decode step measured another way: it should be near decode(1).
        profile["fit"]["verify"] = verify | {
            "stepBaseMs": round(step_base, 4),
            "decode1Ms": round(decode_1, 4),
        }
        # Measured on random-word prompts, so the acceptance rate is a lower bound for real text.
        accepted = sum(r["draft_n_accepted"] for r in spec) / sum(r["draft_n"] for r in spec)
        profile["speculative"] = {"draftStepMs": round(draft_ms, 4), "acceptanceRate": round(accepted, 4)}
    negative = [k for k, v in profile.items() if isinstance(v, float) and v < 0]
    if negative:
        raise SystemExit(f"fit gave negative {negative}: the data doesn't follow the model; look at it first")
    return {k: round(v, 6) if isinstance(v, float) else v for k, v in profile.items()}


def line(xs: list[float], ys: list[float]) -> tuple[float, float, dict]:
    """Least-squares `y = a + b·x` with `a ≥ 0` (a fixed cost can't be negative): a, b, and {r2, samples}."""
    b, a = statistics.linear_regression(xs, ys)
    if a < 0:  # the best line with a ≥ 0 then has a = 0 exactly (the error is convex in a)
        b, a = statistics.linear_regression(xs, ys, proportional=True)
    mean = statistics.fmean(ys)
    ss_res = sum((y - a - b * x) ** 2 for x, y in zip(xs, ys, strict=True))
    ss_tot = sum((y - mean) ** 2 for y in ys)
    return a, b, {"r2": round(1 - ss_res / ss_tot if ss_tot else 1.0, 4), "samples": len(xs)}


def per_token(row: dict) -> float:
    return row["predicted_ms"] / row["predicted_n"]


def step_ms(row: dict) -> float:
    return row["predicted_ms"] / (row["draft_n"] / row["draft_tokens"])


if __name__ == "__main__":
    main()
