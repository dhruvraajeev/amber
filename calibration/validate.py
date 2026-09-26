"""Check Amber's self-hosted LLM model against a llamacpp_bench.py run: real vs Amber, with % error.

    cd backend && uv run python ../calibration/validate.py ../calibration/data/<run> --profile <id>

Every benchmark cell (run kind × concurrency × prompt length) is rebuilt as an Amber design and compared
with the real run on TTFT and end-to-end latency, p50 and p99, in two tables. They replace the block
between the markers in docs/calibration.md; everything else in that file is left alone.

- **Leave one cell out.** Each cell runs on a profile fitted (fit.py, unchanged) to every row *except*
  that cell's, so no cell is graded by coefficients that saw its answers.
- **Same traffic as the benchmark** (replay): `c` calls at once into Amber's GPU scheduler, the next
  round once all return, exactly as llamacpp_bench.py sends them. This grades the GPU model itself.
- **Amber's usual traffic** (open loop): random arrivals at the throughput the benchmark sustained, the
  way a user runs Amber. The benchmark is closed-loop and kept the server full, so at the same rate
  random arrivals queue far longer. That mismatch is reported, not tuned away.
"""

import argparse
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path

from fit import fit, load
from llamacpp_bench import SLOTS

from amber.contracts import Design, RunConfig
from amber.presets import profiles
from amber.sim import graph
from amber.sim.kernel import Environment, Process, ProcessGen
from amber.sim.nodes import llm_selfhosted
from amber.sim.request import Request
from amber.sim.run import execute

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "calibration.md"
START, END = "<!-- validate.py:start -->", "<!-- validate.py:end -->"
# llama-server's default logical batch (-b): the most prompt tokens one step reads across its slots.
MAX_BATCH_TOKENS = 2048
SEEDS, DURATION_S, WARMUP_S = 20, 600, 30  # open loop, pooled per cell: 1,000+ requests even at 0.1 req/s
REPLAY_ROUNDS = 200  # only speculative acceptance is random in a replay
HELD_OUT = "held-out"  # the id the leave-one-out profile runs under


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run", type=Path, help="a calibration/data/<run> folder")
    p.add_argument("--profile", required=True, help="the shared/profiles id fit.py wrote for this run")
    args = p.parse_args()

    profile = profiles()[args.profile]
    rows = load(args.run / "requests.csv")
    compared = [compare(key, cell, rows, profile) for key, cell in cells(rows).items()]
    block = f"{source(profile)}\n\n{REPLAY_HEAD}\n\n" + markdown([c["replay"] for c in compared])
    block += f"\n{OPEN_LOOP_HEAD}\n\n" + markdown([c["openLoop"] for c in compared])
    print(block)
    text = DOC.read_text()
    DOC.write_text(re.sub(f"{START}.*?{END}", lambda _: f"{START}\n{block}{END}", text, flags=re.S))
    print(f"wrote the table into {DOC.relative_to(ROOT)}")


def cells(rows: list[dict]) -> dict[tuple, list[dict]]:
    """The benchmark's rows by cell: (run, draft tokens, concurrency, prompt tokens). `draft` rows time
    the draft model alone; they are an input to the speculative cells, not a cell of their own."""
    by_cell = defaultdict(list)
    for r in rows:
        if r["run"] != "draft":
            key = (r["run"], int(r["draft_tokens"]), int(r["concurrency"]), int(r["prompt_tokens"]))
            by_cell[key].append(r)
    return dict(by_cell)


def throughput_rps(cell: list[dict]) -> float:
    """What the benchmark sustained: its requests over the rounds' total time. A round lasts until its
    slowest request returns, and the next starts right after."""
    rounds = defaultdict(list)
    for r in cell:
        rounds[r["rep"]].append(r["e2e_ms"])
    return len(cell) / sum(max(e2e) for e2e in rounds.values()) * 1000


def compare(key: tuple, cell: list[dict], rows: list[dict], profile: dict) -> dict:
    """One cell, both ways: {"replay": row, "openLoop": row}, each with real, Amber and % errors."""
    run, k, c, prompt = key
    held_out = fit([r for r in rows if r not in cell])
    # Amber reads profiles from one registry built from shared/profiles; the held-out fit joins it under
    # its own id for this cell (graph.validate never sees it: benchmark_design checks the real id).
    llm_selfhosted.PROFILES[HELD_OUT] = llm_selfhosted.TimingProfile(
        prefill_base_ms=held_out["prefillBaseMs"],
        prefill_ms_per_token=held_out["prefillMsPerToken"],
        decode_base_ms=held_out["decodeBaseMs"],
        decode_ms_per_sequence=held_out["decodeMsPerSequence"],
        verify_cost_per_draft_token=held_out["verifyCostPerDraftToken"],
    )
    rps = throughput_rps(cell)
    output = round(statistics.fmean(r["predicted_n"] for r in cell))
    spec = held_out.get("speculative") if run == "speculative" else None
    design = benchmark_design(profile, prompt, output, rps, k, spec)
    label = f"spec k={k}, c={c}, {prompt} tok" if run == "speculative" else f"c={c}, {prompt} tok"
    real = stats([r["ttft_ms"] for r in cell], [r["e2e_ms"] for r in cell])
    base = {"label": label, "samples": len(cell), "rps": rps, "real": real}
    return {
        "replay": row(base, replay(design, c, prompt, output)),
        "openLoop": row(base, open_loop(design)),
    }


def row(base: dict, sim: dict) -> dict:
    return base | {"sim": sim, "errors": {m: (sim[m] - base["real"][m]) / base["real"][m] * 100 for m in sim}}


def replay(design: Design, c: int, prompt: int, output: int) -> dict[str, float]:
    """The benchmark's own traffic through Amber's scheduler: `c` calls at the same instant, the next
    round once all return."""
    env = Environment()
    llm = llm_selfhosted.SelfHostedLlm(env, design.nodes[2], seed=0)
    done: list[Request] = []

    def one(req: Request) -> ProcessGen:
        yield from llm.call(req, prompt, output)
        req.end = env.now
        done.append(req)

    def rounds() -> ProcessGen:
        for i in range(REPLAY_ROUNDS):
            calls = [Process(env, one(Request(f"{i}.{j}", env.now, math.inf))) for j in range(c)]
            yield from calls  # wait for every call in the round

    Process(env, rounds())
    env.run(math.inf)
    return stats([r.first_token_at - r.created_at for r in done], [r.end - r.created_at for r in done])


def open_loop(design: Design) -> dict[str, float]:
    """Amber as a user runs it: random arrivals at the benchmark's measured rate, pooled over seeds."""
    ttft, e2e = [], []
    for seed in range(SEEDS):
        metrics = execute(design, RunConfig(duration_s=DURATION_S, seed=seed, warmup_s=WARMUP_S)).metrics
        for req in metrics.answered():
            ttft.append(req.first_token_at - req.created_at)
            e2e.append(req.end - req.created_at)
    return stats(ttft, e2e)


def benchmark_design(
    profile: dict, prompt: int, output: int, rps: float, k: int, spec: dict | None
) -> Design:
    """users → agent (one LLM call, no tools, so prompt and output sizes are exact) → self-hosted LLM,
    set up like the benchmark's llama-server: `SLOTS` sequences at once, KV reserved for the output."""
    llm = {
        "mode": "selfHosted",
        "gpuPresetId": profile["gpuPresetId"],
        "modelPresetId": profile["modelPresetId"],
        "profileId": profile["id"],
        "replicas": 1,
        "maxBatchSize": SLOTS,
        "maxBatchTokens": MAX_BATCH_TOKENS,
        "maxOutputTokensReserve": output,
        "speculative": {
            "enabled": spec is not None,
            "draftTokens": k or 1,
            "acceptanceRate": spec["acceptanceRate"] if spec else 0.5,
            "draftStepMs": spec["draftStepMs"] if spec else 1,
        },
    }
    raw = {
        "name": "calibration cell",
        "version": 1,
        "nodes": [
            node("users", "users", {"traffic": {"type": "constant", "rps": rps}, "clientTimeoutMs": 3.6e6}),
            node(
                "agent",
                "agent",
                {
                    "llmCallsMean": 1,
                    "toolCallsPerStep": 0,
                    "toolLatency": {"p50Ms": 1, "p99Ms": 2},
                    "basePromptTokens": prompt,
                    "contextGrowthTokensPerStep": 0,
                    "outputTokensPerCall": output,
                },
            ),  # fmt: skip
            node("llm", "llm", llm),
        ],
        "edges": [
            {"id": "e1", "source": "users", "target": "agent"},
            {"id": "e2", "source": "agent", "target": "llm", "role": "llm"},
        ],
    }
    if issues := graph.validate(raw):  # checked with the real profile id, then run with the held-out one
        raise SystemExit(f"benchmark design is invalid: {issues}")
    raw["nodes"][2]["params"]["profileId"] = HELD_OUT
    return Design.model_validate(raw)


def node(node_id: str, kind: str, params: dict) -> dict:
    return {"id": node_id, "kind": kind, "label": node_id, "position": {"x": 0, "y": 0}, "params": params}


def stats(ttft: list[float], e2e: list[float]) -> dict[str, float]:
    return {
        "ttftP50": pct(ttft, 50),
        "ttftP99": pct(ttft, 99),
        "e2eP50": pct(e2e, 50),
        "e2eP99": pct(e2e, 99),
    }


def pct(values: list[float], q: int) -> float:
    """The q-th percentile, the way Amber's summary computes it (inclusive, interpolated)."""
    if len(values) < 2:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[q - 1]


REPLAY_HEAD = (
    "### Same traffic as the benchmark\n\n"
    "Amber's GPU scheduler fed the benchmark's own rounds: this grades the GPU model itself."
)
OPEN_LOOP_HEAD = (
    "### Amber's usual traffic, at the benchmark's throughput\n\n"
    "Random arrivals at the rate each cell sustained: this is how a user runs Amber, and where the "
    "closed- vs open-loop mismatch shows."
)


def source(profile: dict) -> str:
    return (
        f"Profile `{profile['id']}` · {profile['hardware']} · {profile['server']} · "
        f"measured {profile['measuredAt']} · generated by `calibration/validate.py`"
    )


def markdown(table: list[dict]) -> str:
    """A real vs Amber table, ms and % error (+ means Amber is slower than reality), and its summary."""
    out = [
        "| Cell | Real n | Req/s | TTFT p50 real / Amber | TTFT p99 real / Amber "
        "| E2E p50 real / Amber | E2E p99 real / Amber |",
        "|---|---:|---:|---|---|---|---|",
    ]
    for line in table:
        real, sim, err = line["real"], line["sim"], line["errors"]
        out.append(
            f"| {line['label']} | {line['samples']} | {line['rps']:.2f} | "
            + " | ".join(f"{real[m]:,.0f} / {sim[m]:,.0f} ({err[m]:+.0f}%)" for m in real)
            + " |"
        )
    worst = {m: max(abs(line["errors"][m]) for line in table) for m in table[0]["errors"]}
    median = {m: statistics.median(abs(line["errors"][m]) for line in table) for m in table[0]["errors"]}
    out += [
        "",
        "| Across all cells | TTFT p50 | TTFT p99 | E2E p50 | E2E p99 |",
        "|---|---:|---:|---:|---:|",
        "| Median \\|error\\| | " + " | ".join(f"{median[m]:.0f}%" for m in median) + " |",
        "| Worst \\|error\\| | " + " | ".join(f"{worst[m]:.0f}%" for m in worst) + " |",
        "",
    ]
    return "\n".join(out)


if __name__ == "__main__":
    main()
