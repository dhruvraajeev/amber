"""Time a hosted LLM API: the measurements behind Amber's hosted LLM presets.

    python3 calibration/hosted_bench.py --model <provider model id>            # Groq, key from GROQ_API_KEY
    python3 calibration/hosted_bench.py --model <id> --base-url <url> --key-env NIM_API_KEY

Standard library only. Talks to any OpenAI-compatible chat completions API (Groq by default). Sends
`--requests` streaming calls one at a time, `--interval-s` apart so they stay under the free tier's
requests-per-minute limit, each with a prompt of random words nobody has sent before (so no provider
cache helps) and a `max_tokens` cap. The prompt and output sizes come from an Amber hosted preset, so the
measurement matches what Amber simulates.

Per call it records, client side, TTFT from the moment the request is written to an already-open
connection, end-to-end time and output tokens/sec; the provider's own timings when it reports them (Groq:
`queue_time`, `prompt_time`, `completion_time`, `total_time`, in seconds, in the last streamed chunk under
`x_groq.usage`, or `usage`); and the `x-ratelimit-*` response headers. A 429 is waited out (`retry-after`)
and retried, and counted. Rows go to calibration/data/<name>/requests.csv with meta.json beside it. The key
is read from the environment, or from the repo's .env; it is never written anywhere.
"""

import argparse
import csv
import http.client
import json
import os
import random
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

CALIBRATION = Path(__file__).resolve().parent
ROOT = CALIBRATION.parent
GROQ = "https://api.groq.com/openai/v1"
# The provider's own per-request timings, in seconds (Groq's `usage` names).
SERVER_FIELDS = "queue_time prompt_time completion_time total_time".split()
# Rate-limit response header → its CSV column (`x-ratelimit-remaining-requests` → `remaining_requests`).
RATE_COLUMNS = {
    f"x-ratelimit-{kind}-{unit}": f"{kind}_{unit}"
    for unit in ("requests", "tokens")
    for kind in ("limit", "remaining", "reset")
}
FIELDS = (
    "i status retries prompt_tokens completion_tokens finish_reason ttft_ms e2e_ms client_tps".split()
    + SERVER_FIELDS
    + list(RATE_COLUMNS.values())
)
MAX_RETRIES = 5
WORDS = (
    "river stone lantern orbit velvet copper meadow signal harbor quartz ember canyon whisper ledger "
    "falcon cobalt thistle marble glacier compass saffron tundra beacon willow cipher prairie anvil "
    "lagoon summit granite nectar pylon cedar mosaic vapor ridge atlas fern tide circuit plume basalt"
).split()


def main() -> None:
    args = parse_args()
    key = api_key(args.key_env)
    preset = presets()[args.preset]
    prompt_tokens, output_tokens = preset["defaultPromptTokens"], preset["defaultOutputTokens"]
    out = CALIBRATION / "data" / args.name
    out.mkdir(parents=True, exist_ok=True)
    (out / "meta.json").write_text(
        json.dumps(
            {
                "provider": urlsplit(args.base_url).hostname,
                "baseUrl": args.base_url,
                "model": args.model,
                "preset": args.preset,
                "promptTokens": prompt_tokens,
                "outputTokens": output_tokens,
                "requests": args.requests,
                "intervalS": args.interval_s,
                "date": date.today().isoformat(),
            },
            indent=2,
        )
        + "\n"
    )
    rng = random.Random(f"{args.model}:{date.today()}")
    with (out / "requests.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, FIELDS)
        writer.writeheader()
        for i in range(args.requests):
            started = time.monotonic()
            text = prompt(prompt_tokens, rng)
            row = {"i": i} | complete(args.base_url, key, args.model, text, output_tokens)
            check(row)
            writer.writerow(row)
            f.flush()
            print(f"{i + 1}/{args.requests}  ttft {row['ttft_ms']:.0f} ms  {row['client_tps']:.0f} tok/s")
            if i + 1 < args.requests:
                time.sleep(max(0.0, args.interval_s - (time.monotonic() - started)))
    print(f"wrote {out.relative_to(ROOT)}/requests.csv")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", required=True, help="the provider's model id (check its model list)")
    p.add_argument("--base-url", default=GROQ, help="an OpenAI-compatible API base (default: Groq)")
    p.add_argument("--key-env", default="GROQ_API_KEY", help="env variable (or .env line) with the key")
    p.add_argument("--preset", default="hosted-small-paid", help="hosted_llms.json id for the sizes")
    p.add_argument("--requests", type=int, default=100)
    # ~770 tokens a call × 7.5 calls/min stays under a 6K tokens/min free-tier cap (check your model's).
    p.add_argument("--interval-s", type=float, default=8.0, help="seconds between call starts")
    p.add_argument("--name", help="folder under calibration/data (default: <host>-<model>)")
    args = p.parse_args()
    host = urlsplit(args.base_url).hostname or "api"
    args.name = args.name or f"{host.split('.')[-2]}-{args.model.replace('/', '-')}"
    return args


def api_key(env: str) -> str:
    """The key from the environment, else from a `NAME=value` line in the repo's .env (gitignored)."""
    if key := os.environ.get(env):
        return key
    dotenv = ROOT / ".env"
    for line in dotenv.read_text().splitlines() if dotenv.exists() else []:
        name, _, value = line.partition("=")
        if name.strip() == env and value.strip():
            return value.strip().strip("'\"")
    raise SystemExit(f"{env} is not set: put it in your shell or in {dotenv.relative_to(ROOT)}")


def presets() -> dict[str, dict]:
    return {p["id"]: p for p in json.loads((ROOT / "shared" / "presets" / "hosted_llms.json").read_text())}


def prompt(tokens: int, rng: random.Random) -> str:
    """Random words, about `tokens` long (usage reports the real count), ending in an ask for a long answer
    so the reply runs to `max_tokens`. A fresh nonce keeps any provider-side prompt cache cold."""
    words = " ".join(rng.choice(WORDS) for _ in range(tokens * 3 // 4))
    ask = "Write a long, detailed story using these words. Do not stop early."
    return f"[{rng.getrandbits(64):x}] {words}\n\n{ask}"


def complete(base_url: str, key: str, model: str, text: str, max_tokens: int) -> dict:
    """One streamed chat completion, retried after each 429 up to MAX_RETRIES times: client-side times,
    the provider's timings from the last chunk, and the rate-limit headers of the answered call."""
    url = urlsplit(base_url)
    body = json.dumps({
        "model": model, "messages": [{"role": "user", "content": text}], "max_tokens": max_tokens,
        "temperature": 1.0, "stream": True, "stream_options": {"include_usage": True},
    })  # fmt: skip
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    for retries in range(MAX_RETRIES + 1):
        conn_type = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
        conn = conn_type(url.hostname, url.port, timeout=120)
        conn.connect()  # connected before the clock starts: TTFT runs from the request being sent
        sent = time.perf_counter()
        conn.request("POST", f"{url.path.rstrip('/')}/chat/completions", body, headers)
        resp = conn.getresponse()
        if resp.status == 429:
            wait = float(resp.getheader("retry-after") or 2**retries)
            resp.read()
            conn.close()
            print(f"429: waiting {wait:.1f} s")
            time.sleep(wait)
            continue
        if resp.status != 200:
            raise SystemExit(f"HTTP {resp.status}: {resp.read()[:500].decode(errors='replace')}")
        first = last = None
        usage: dict = {}
        finish = ""
        for line in resp:
            if not line.startswith(b"data: ") or line.strip() == b"data: [DONE]":
                continue
            chunk = json.loads(line[6:])
            for choice in chunk.get("choices", []):
                if choice.get("delta", {}).get("content"):
                    last = time.perf_counter()
                    first = first or last
                finish = choice.get("finish_reason") or finish
            usage = chunk.get("x_groq", {}).get("usage") or chunk.get("usage") or usage
        conn.close()
        if first is None:
            raise SystemExit("no tokens streamed back")
        n = usage.get("completion_tokens", 0)
        row = {
            "status": resp.status,
            "retries": retries,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": n,
            "finish_reason": finish,
            "ttft_ms": round((first - sent) * 1000, 3),
            "e2e_ms": round((last - sent) * 1000, 3),
            "client_tps": round((n - 1) / (last - first), 3) if n > 1 and last > first else 0.0,
        }
        row |= {k: usage.get(k, "") for k in SERVER_FIELDS}  # blank when the provider doesn't report it
        return row | {col: resp.getheader(header, "") for header, col in RATE_COLUMNS.items()}
    raise SystemExit(f"still rate-limited after {MAX_RETRIES} retries: raise --interval-s")


def check(row: dict) -> None:
    """Usable only if the times are positive and ordered, and the provider counted tokens both ways."""
    measured = ("ttft_ms", "e2e_ms", "prompt_tokens", "completion_tokens")
    problems = [key for key in measured if not row[key] > 0]
    if row["e2e_ms"] < row["ttft_ms"]:
        problems.append("finished before its first token")
    if problems:
        raise SystemExit(f"bad measurement {row}: {', '.join(problems)}")


if __name__ == "__main__":
    main()
