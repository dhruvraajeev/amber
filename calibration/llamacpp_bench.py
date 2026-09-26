"""Time llama.cpp's server under load: the measurements behind Amber's self-hosted LLM profiles.

    brew install llama.cpp
    python3 calibration/llamacpp_bench.py \\
        --model calibration/models/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf \\
        --draft calibration/models/Llama-3.2-1B-Instruct-Q4_K_M.gguf

Standard library only; macOS only (it reads the chip from sysctl). Three kinds of run, each against a
fresh `llama-server` with 8 parallel slots (continuous batching, like vLLM):

- `base`: every concurrency (1, 2, 4, 8) × prompt length (128, 512, 2048), `--reps` rounds each.
  A round sends `c` requests at the same instant and waits for all of them.
- `draft` (with --draft): the draft model alone, one request at a time, for its per-token cost.
- `speculative` (with --draft): the model checking 2, 4 and 8 draft tokens a step, one request at a time.

Every request asks for exactly `--n-predict` tokens (`ignore_eos`) from a prompt of random words nobody
has sent before, with the prompt cache off, so each one pays for its full prefill. TTFT is timed from
the moment the request is written to an already-open connection. Rows go to
calibration/data/<name>/requests.csv (written as they arrive) with meta.json beside it; server logs go
to the gitignored calibration/raw/. fit.py turns a run into a profile.
"""

import argparse
import csv
import http.client
import json
import random
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
from pathlib import Path

CALIBRATION = Path(__file__).resolve().parent
CONCURRENCY = (1, 2, 4, 8)
PROMPT_TOKENS = (128, 512, 2048)
DRAFT_TOKENS = (2, 4, 8)
SLOTS = max(CONCURRENCY)
# The server's own per-request `timings` (llama.cpp tools/server, server_slot_stats::to_json).
SERVER_FIELDS = "prompt_n cache_n prompt_ms predicted_n predicted_ms draft_n draft_n_accepted".split()
FIELDS = (
    "run draft_tokens concurrency prompt_tokens rep ttft_ms e2e_ms client_ms_per_token".split()
    + SERVER_FIELDS
)
WORDS = (
    "river stone lantern orbit velvet copper meadow signal harbor quartz ember canyon whisper ledger "
    "falcon cobalt thistle marble glacier compass saffron tundra beacon willow cipher prairie anvil "
    "lagoon summit granite nectar pylon cedar mosaic vapor ridge atlas fern tide circuit plume basalt"
).split()


def main() -> None:
    args = parse_args()
    out = CALIBRATION / "data" / args.name
    out.mkdir(parents=True, exist_ok=True)
    (CALIBRATION / "raw").mkdir(exist_ok=True)
    base_cmd = server_cmd(args, args.model)
    (out / "meta.json").write_text(
        json.dumps(
            {
                "model": args.model.name,
                "draftModel": args.draft.name if args.draft else None,
                "hardware": hardware(),
                "server": version(args.llama_server),
                "command": " ".join(base_cmd),
                "nPredict": args.n_predict,
                "reps": args.reps,
                "date": date.today().isoformat(),
            },
            indent=2,
        )
        + "\n"
    )

    with (out / "requests.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, FIELDS)
        writer.writeheader()

        def record(rows: list[dict]) -> None:
            writer.writerows(rows)
            f.flush()

        with serve(base_cmd, args.port, "base"):
            for prompt in PROMPT_TOKENS:
                for c in CONCURRENCY:
                    for rep in range(args.reps):
                        record(round_(args, "base", 0, c, prompt, rep))
                        print(f"base  c={c} prompt={prompt} rep={rep}")
        if not args.draft:
            return
        with serve(server_cmd(args, args.draft), args.port, "draft"):
            for rep in range(args.reps):
                record(round_(args, "draft", 0, 1, PROMPT_TOKENS[0], rep))
        for k in DRAFT_TOKENS:
            # min = max and no probability cut-off: every step drafts and checks exactly k tokens.
            spec = ["-md", str(args.draft), "--spec-draft-n-max", str(k), "--spec-draft-n-min", str(k)]
            with serve(base_cmd + [*spec, "--spec-draft-p-min", "0"], args.port, f"spec-k{k}"):
                for rep in range(args.reps):
                    record(round_(args, "speculative", k, 1, PROMPT_TOKENS[0], rep))
                    print(f"spec  k={k} rep={rep}")
    print(f"wrote {out.relative_to(CALIBRATION.parent)}/requests.csv; next: calibration/fit.py")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", type=Path, required=True, help="the GGUF to measure")
    p.add_argument("--draft", type=Path, help="a smaller GGUF of the same family, for speculative runs")
    p.add_argument("--name", help="folder under calibration/data (default: the model file's name)")
    p.add_argument("--reps", type=int, default=3, help="rounds per concurrency × prompt length")
    p.add_argument("--n-predict", type=int, default=128, help="output tokens per request")
    p.add_argument("--port", type=int, default=8089)
    p.add_argument("--llama-server", default="llama-server", help="path to the llama-server binary")
    args = p.parse_args()
    args.name = args.name or args.model.stem
    return args


def server_cmd(args: argparse.Namespace, model: Path) -> list[str]:
    # Each slot gets its own share of the context: room for the longest prompt, the output, and slack.
    ctx = SLOTS * (max(PROMPT_TOKENS) + args.n_predict + 256)
    return [args.llama_server, "-m", str(model), "--port", str(args.port), "-np", str(SLOTS), "-c", str(ctx),
            "-ngl", "99", "--no-webui"]  # fmt: skip


@contextmanager
def serve(cmd: list[str], port: int, label: str):
    """A llama-server for the duration of the block, warmed up by one request; its log goes to raw/."""
    log_path = CALIBRATION / "raw" / f"server-{label}.log"
    with log_path.open("w") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
        try:
            wait_healthy(proc, port, log_path)
            complete(port, prompt_tokens(port, 64, random.Random(label)), 8)  # compiles Metal kernels
            yield
        finally:
            proc.terminate()
            proc.wait()


def wait_healthy(proc: subprocess.Popen, port: int, log_path: Path, timeout_s: float = 300) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"llama-server exited; last lines of {log_path}:\n" + tail(log_path))
        try:
            if request(port, "GET", "/health")[0] == 200:
                return
        except OSError:
            pass  # not listening yet
        time.sleep(0.5)
    raise SystemExit(f"llama-server not healthy after {timeout_s:.0f} s; see {log_path}")


def round_(args: argparse.Namespace, run: str, k: int, c: int, prompt: int, rep: int) -> list[dict]:
    """`c` requests released together; one checked row each."""
    rng = random.Random(f"{run}:{k}:{c}:{prompt}:{rep}")
    prompts = [prompt_tokens(args.port, prompt, rng) for _ in range(c)]
    start = threading.Barrier(c)
    with ThreadPoolExecutor(c) as pool:  # map re-raises a request's failure here
        results = list(pool.map(lambda p: complete(args.port, p, args.n_predict, start), prompts))
    rows = [
        {"run": run, "draft_tokens": k, "concurrency": c, "prompt_tokens": prompt, "rep": rep, **r}
        for r in results
    ]
    for row in rows:
        check(row, args.n_predict)
    return rows


def prompt_tokens(port: int, n: int, rng: random.Random) -> list[int]:
    """Exactly `n` token ids of random words. Every word is at least one token, so `n` words is enough."""
    text = " ".join(rng.choice(WORDS) for _ in range(n))
    return json.loads(request(port, "POST", "/tokenize", {"content": text})[1])["tokens"][:n]


def complete(port: int, prompt: list[int], n_predict: int, start: threading.Barrier | None = None) -> dict:
    """One streamed /completion. Client-side times, plus the server's own `timings` from the last event."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=600)
    conn.connect()  # connected before the clock starts: TTFT runs from the request being sent
    body = json.dumps({"prompt": prompt, "n_predict": n_predict, "ignore_eos": True, "stream": True,
                       "cache_prompt": False})  # fmt: skip
    if start:
        start.wait()
    sent = time.perf_counter()
    conn.request("POST", "/completion", body, {"Content-Type": "application/json"})
    resp = conn.getresponse()
    first = last = None
    timings: dict = {}
    for line in resp:
        if not line.startswith(b"data: "):
            continue
        event = json.loads(line[6:])
        if event.get("content") or event.get("tokens"):
            last = time.perf_counter()
            first = first or last
        if event.get("stop"):
            timings = event.get("timings", {})
            break
    conn.close()
    if first is None:
        raise SystemExit(f"no tokens streamed back (HTTP {resp.status})")
    n = timings.get("predicted_n", 0)
    times = {
        "ttft_ms": (first - sent) * 1000,
        "e2e_ms": (last - sent) * 1000,
        "client_ms_per_token": (last - first) * 1000 / max(n - 1, 1),
    } | {key: timings.get(key, 0) for key in SERVER_FIELDS}
    return {k: round(v, 3) for k, v in times.items()}


def check(row: dict, n_predict: int) -> None:
    """The data is only usable if every time is positive and every request paid its full prefill."""
    problems = [key for key in ("ttft_ms", "e2e_ms", "prompt_ms", "predicted_ms") if not row[key] > 0]
    if row["cache_n"] or row["prompt_n"] < row["prompt_tokens"]:
        problems.append(f"prompt cache used ({row['cache_n']} cached, {row['prompt_n']} read)")
    if row["predicted_n"] != n_predict:
        problems.append(f"predicted_n {row['predicted_n']} != {n_predict}")
    if row["run"] == "speculative" and not row["draft_n"]:
        problems.append("no draft tokens: speculative decoding did not run")
    if problems:
        raise SystemExit(f"bad measurement {row}: {', '.join(problems)}")


def request(port: int, method: str, path: str, payload: dict | None = None) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    try:
        conn.request(
            method, path, json.dumps(payload) if payload else None, {"Content-Type": "application/json"}
        )
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def hardware() -> str:
    """e.g. "Apple M4 Pro, 20-core GPU, 24 GB unified memory"."""
    chip = sh("sysctl", "-n", "machdep.cpu.brand_string")
    memory_gb = int(sh("sysctl", "-n", "hw.memsize")) // 2**30
    cores = re.search(r"Total Number of Cores: (\d+)", sh("system_profiler", "SPDisplaysDataType"))
    return f"{chip}, {cores[1] if cores else '?'}-core GPU, {memory_gb} GB unified memory"


def version(llama_server: str) -> str:
    out = subprocess.run([llama_server, "--version"], capture_output=True, text=True)
    return next(
        (line for line in (out.stdout + out.stderr).splitlines() if line.startswith("version")), "unknown"
    )


def sh(*cmd: str) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()


def tail(path: Path, lines: int = 20) -> str:
    return "\n".join(path.read_text().splitlines()[-lines:])


if __name__ == "__main__":
    main()
