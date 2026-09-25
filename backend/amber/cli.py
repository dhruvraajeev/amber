"""Run a design from the command line, without the frontend or the API (plan §18).

    uv run python -m amber.cli ../shared/templates/classic-web-app.json --duration 60 --seed 1

It validates the design exactly as the API will (§7.6), prints what happened in plain English, and
with `--out` writes the whole RunResult as JSON.
"""

import argparse
import json
import sys
from pathlib import Path

from amber.contracts import Design, RunConfig, RunResult
from amber.sim.graph import validate
from amber.sim.run import simulate


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    raw_design = json.loads(Path(args.design).read_text())
    raw_config = {"durationS": args.duration, "seed": args.seed, "warmupS": args.warmup}

    if issues := validate(raw_design, raw_config):
        print(f"{args.design} can't run:", file=sys.stderr)
        for issue in issues:
            where = issue.node_id or issue.edge_id or issue.path or ""
            print(f"  {issue.code:<16} {where:<12} {issue.message}", file=sys.stderr)
        return 2

    result = simulate(Design.model_validate(raw_design), RunConfig.model_validate(raw_config))
    print(report(result, raw_design["name"]))
    if args.out:
        Path(args.out).write_text(result.model_dump_json(indent=2))
        print(f"\nFull result written to {args.out}")
    return 0


def report(result: RunResult, name: str) -> str:
    """The run in about twenty lines: what came in, how it went, what it would cost, what to fix."""
    s, e = result.summary, result.engine
    lines = [
        f"{name} — {result.config.duration_s:g} s at seed {result.config.seed}"
        f" (warmup {result.config.warmup_s:g} s, excluded below)",
        f"  {e.simulated_requests} requests simulated in {e.wall_ms:.0f} ms"
        f" ({e.events} events, {e.events_per_sec / 1000:.0f}k/s)",
        "",
        f"  requests    {s.requests}  ({s.throughput_rps:.1f}/s answered)",
        f"  errors      {s.errors} rejected/rate-limited, {s.timeouts} timed out"
        f"  ({100 * s.error_rate:.1f}% not ok)",
        f"  latency     p50 {s.latency_ms.p50:.0f} ms · p95 {s.latency_ms.p95:.0f} ms"
        f" · p99 {s.latency_ms.p99:.0f} ms · max {s.latency_ms.max:.0f} ms",
    ]
    if s.ttft_ms:
        lines.append(f"  first token p50 {s.ttft_ms.p50:.0f} ms · p99 {s.ttft_ms.p99:.0f} ms")

    lines += ["", "  nodes"]
    for node in result.nodes:
        lines.append(
            f"    {node.id:<12} {node.kind:<13} busy {100 * node.util_avg:5.1f}%"
            f" (peak {100 * node.util_max:5.1f}%)  queue max {node.queue_max:.0f}"
            f"  rejected {node.rejects}  ${node.monthly_usd:,.2f}/mo"
        )

    lines += ["", f"  cost        ${result.cost.monthly_total_usd:,.2f}/month"]
    lines += [f"    {a}" for a in result.cost.assumptions]

    lines += ["", "  findings"]
    lines += [f"    [{b.severity}] {b.message}" for b in result.bottlenecks]

    if result.attribution:
        lines += ["", "  where the slowest 1% of requests spend their time"]
        for row in result.attribution[:5]:
            share = row.queue_share + row.work_share
            lines.append(
                f"    {row.node_id:<12} {100 * share:5.1f}%"
                f"  (waiting {100 * row.queue_share:.1f}%, working {100 * row.work_share:.1f}%)"
            )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="amber", description="Simulate an Amber design.")
    p.add_argument("design", help="path to a design JSON file (shared/templates has three)")
    p.add_argument("--duration", type=float, default=60, help="simulated seconds, 10-600 (default 60)")
    p.add_argument("--seed", type=int, default=1, help="same design + config + seed => same result")
    p.add_argument("--warmup", type=float, default=5, help="seconds left out of the summary (default 5)")
    p.add_argument("--out", help="also write the full RunResult JSON here")
    return p


if __name__ == "__main__":
    raise SystemExit(main())
