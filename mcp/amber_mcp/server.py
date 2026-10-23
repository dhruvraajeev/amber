"""Amber's MCP server (plan §13): lets an AI agent list templates, check a design, run it, and time the real
endpoints a design depends on, so its latencies are measured rather than guessed.

Every tool is a thin wrapper over Amber's public REST API; nothing here simulates. `AMBER_API_URL` picks
the API (default: the live deploy), which also serves the editor that `open_url` links to. The
`model_codebase` prompt walks an agent through turning the repo it is working in into a design.
Run with `amber-mcp`, which speaks MCP over stdio.
"""

import base64
import json
import logging
import os
import statistics
import time
import zlib
from importlib.metadata import version
from urllib.parse import urlsplit

import anyio
import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

API_URL = os.environ.get(
    "AMBER_API_URL", "https://amber.victoriousrock-f5544b42.westus.azurecontainerapps.io"
).rstrip("/")
logging.getLogger("httpx").setLevel(logging.WARNING)  # not a log line per request on the client's stderr
TIMEOUT_S = 60  # a run may take 20 s, plus waiting for a turn, plus a cold start from zero replicas

# measure_latency: polite by construction, since it times other people's servers.
MAX_SAMPLES = 100
GAP_S = 0.2  # at least this long between request starts: never more than 5 requests a second to one host
REQUEST_TIMEOUT_S = 10
BUDGET_S = 60  # stop sampling after this long and report what was measured

DESIGN_GUIDE = """
A design is JSON: {"name": str, "version": 1, "nodes": [...], "edges": [...]}.
Node: {"id": str, "kind": str, "label": str, "params": {...}} ("position" is optional here).
Edge: {"id": str, "source": node id, "target": node id}; an agent's edges also need "role": "llm"|"tool".
Latencies are {"p50Ms": n, "p99Ms": n} with p99 >= p50 > 0.
Kinds and params:
- users: traffic ({"type":"constant","rps"} | {"type":"ramp","startRps","endRps"}
  | {"type":"spike","baseRps","peakRps","peakStartS","peakDurationS"}), clientTimeoutMs.
  Exactly 1 outgoing edge.
- loadBalancer: algorithm ("roundRobin"|"leastConnections"), overhead. 1+ outgoing.
- service: replicas (1-50), concurrencyPerReplica, queueLimit, work, costPerReplicaMonth. Calls every
  outgoing edge in order.
- cache: hitRate (0-1), latency, costPerMonth. Exactly 1 outgoing (the miss path).
- database: preset ("postgres"|"mongodb"|"vector"|"custom"), connectionPool, queueLimit, query, costPerMonth.
  Leaf.
- agent: llmCallsMean, toolCallsPerStep, toolLatency, basePromptTokens, contextGrowthTokensPerStep,
  outputTokensPerCall. Exactly 1 edge with role "llm" to an llm node; any number with role "tool".
- llm (leaf), hosted: mode "hosted", presetId, ttft, tokensPerSecond {"p50","p99Low"}, inputUsdPer1M,
  outputUsdPer1M, rateLimitRpm, maxRetries.
  Token sizes are not llm params: a call from an agent uses the agent's basePromptTokens and
  outputTokensPerCall; a call from anything else uses the preset's defaultPromptTokens/defaultOutputTokens.
- llm, self-hosted: mode "selfHosted", gpuPresetId, modelPresetId, profileId, replicas,
  maxBatchSize, maxBatchTokens, maxOutputTokensReserve,
  speculative {"enabled","draftTokens","acceptanceRate","draftStepMs"}.
  Speed comes from profileId alone: a measured profile from get_presets when its gpuPresetId and
  modelPresetId match the node's, else "default" (an estimate). The GPU sets only memory (how many
  requests fit in the KV cache at once) and price. So a faster GPU is not faster here: add replicas, raise
  maxBatchSize/maxBatchTokens, or enable speculative decoding.
Numbers from a real codebase:
- concurrencyPerReplica is requests truly running at once. CPU-bound Python threads share one core (the
  GIL): use 1 per process and count processes/workers as replicas. Async I/O-bound servers can be high.
- Use latencies measured under load, not on an idle machine; if you can't, say so.
- If any node is over 80% busy, warn that its p99 is fragile: at 90% busy, +10% latency roughly doubles it.
Users traffic and agent params describe the workload: to meet a target, change capacity (replicas, pools,
batch sizes, cache hitRate) and keep the workload as asked unless told otherwise.
Modeling tips:
- One design can have several users nodes. For a traffic mix (e.g. 80% reads, 20% writes), give each
  endpoint its own users node with its share of the rps and its own service node, and let both paths
  share the database, cache or llm nodes downstream. Keep it one design, so shared nodes see all load.
- To give one plain LLM call (no agent loop) its real prompt and output sizes, which drive hosted cost
  and GPU memory, route it through an agent node with llmCallsMean 1, toolCallsPerStep 0,
  contextGrowthTokensPerStep 0, and basePromptTokens/outputTokensPerCall set from the code.
Preset ids come from get_presets; list_templates has complete examples to start from.
The graph must be acyclic and every node reachable from a users node.
Minimal example:
{"name": "Tiny", "version": 1,
 "nodes": [
  {"id": "u", "kind": "users", "label": "Users",
   "params": {"traffic": {"type": "constant", "rps": 50}, "clientTimeoutMs": 5000}},
  {"id": "api", "kind": "service", "label": "API",
   "params": {"replicas": 2, "concurrencyPerReplica": 20, "queueLimit": 100,
              "work": {"p50Ms": 20, "p99Ms": 100}, "costPerReplicaMonth": 30}},
  {"id": "db", "kind": "database", "label": "DB",
   "params": {"preset": "postgres", "connectionPool": 20, "queueLimit": 100,
              "query": {"p50Ms": 5, "p99Ms": 30}, "costPerMonth": 60}}],
 "edges": [{"id": "e1", "source": "u", "target": "api"}, {"id": "e2", "source": "api", "target": "db"}]}
"""

server = MCPServer(
    "amber",
    version=version("amber-mcp"),
    instructions="Amber simulates web and AI system designs: latency percentiles, errors, bottlenecks, "
    "and monthly cost. Start from list_templates, check with validate_design, then simulate.",
)


@server.tool()
async def list_templates() -> list[dict]:
    """Amber's starter designs, complete and valid. Copy one, change it, and pass it to simulate."""
    templates = await _call("GET", "/api/templates")
    return [{**t, "nodes": [_without(n, "position") for n in t["nodes"]]} for t in templates]


@server.tool()
async def get_presets() -> dict:
    """The preset ids a design can name: gpus, models and timing profiles (for self-hosted llm nodes),
    hostedLlms (for hosted llm nodes), databases and services (typical params). Prices are estimates."""
    presets = await _call("GET", "/api/presets")
    return {kind: [_without(p, "note", "verifiedAt") for p in items] for kind, items in presets.items()}


@server.tool(description="Checks a design without running it and returns every problem.\n" + DESIGN_GUIDE)
async def validate_design(design: dict | str) -> dict:
    issues = (await _call("POST", "/api/validate", {"design": _design(design)}))["issues"]
    return {"valid": not issues, "issues": issues}


@server.tool(
    description="Runs a design for duration_s simulated seconds (10-600). Returns the summary (latency "
    "percentiles, throughput, and errorRate, which counts errors, timeouts and rejections), the bottlenecks "
    "found, the monthly cost, and open_url: a link that opens this design in Amber's editor, laid out on the "
    "canvas, where the user can run it and watch it. Give the user the open_url of the design you settle on. "
    "The same design and seed always give the same result.\n" + DESIGN_GUIDE
)
async def simulate(design: dict | str, duration_s: float = 60, seed: int = 42) -> dict:
    design = _design(design)
    body = {"design": design, "config": {"durationS": duration_s, "seed": seed}}
    result = await _call("POST", "/api/simulate", body)
    trimmed = {key: result[key] for key in ("summary", "bottlenecks", "cost")}  # never the timeline: too big
    return {**trimmed, "open_url": open_url(design)}


@server.tool()
async def measure_latency(url: str, samples: int = 30) -> dict:
    """Times real GET requests to one URL and returns latency ready for a node's params, so a design uses
    measured numbers instead of guesses. Use it on the public endpoints a codebase calls (package
    registries, public APIs, the app's own deployed read-only routes) before simulating.

    GET only, never with credentials or custom headers: don't use it on endpoints that need an API key or
    that change anything. Requests run one at a time, at most 5 a second, within 60 s, from this machine,
    so each sample includes this machine's internet trip; a call made between servers in one cloud region
    is faster. Returns p50/p99 in ms (the p99 is rough below 100 samples), how many requests failed, and
    `latency` ({"p50Ms","p99Ms"}) to paste into a service, database or cache node."""
    _check_url(url)
    samples = max(5, min(samples, MAX_SAMPLES))
    times_ms: list[float] = []
    statuses: dict[str, int] = {}
    deadline = time.monotonic() + BUDGET_S
    # One client, so connections are kept alive like a real service's HTTP pool. The first request pays
    # for DNS and TLS and is thrown away (warm-up), so the samples are steady-state calls.
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S, follow_redirects=True) as client:
        for i in range(samples + 1):
            if time.monotonic() > deadline:
                break
            started = time.perf_counter()
            try:
                response = await client.get(url)
                status = str(response.status_code)
            except httpx.HTTPError as e:
                status = type(e).__name__
            elapsed_ms = (time.perf_counter() - started) * 1000
            if i:  # 0 is the warm-up
                statuses[status] = statuses.get(status, 0) + 1
                if status.startswith("2"):
                    times_ms.append(elapsed_ms)
            if status == "429":  # the server asked us to slow down: stop here, keep what was measured
                break
            await anyio.sleep(max(0.0, GAP_S - elapsed_ms / 1000))
    if not times_ms:
        raise ToolError(
            f"No successful response from {url} ({_counts(statuses)}). Keep this latency assumed."
        )
    return {
        "url": url,
        **latency_summary(times_ms),
        "failed": sum(statuses.values()) - len(times_ms),
        "statuses": statuses,
    }


def latency_summary(times_ms: list[float]) -> dict:
    """p50/p99 (inclusive quantiles, as the simulator computes them), min, max, and `latency` for a node."""
    ordered = sorted(times_ms)
    if len(ordered) > 1:
        cuts = statistics.quantiles(ordered, n=100, method="inclusive")
        p50, p99 = cuts[49], cuts[98]
    else:
        p50 = p99 = ordered[0]
    p50, p99 = round(max(p50, 0.1), 1), round(max(p99, p50, 0.1), 1)
    return {
        "samples": len(ordered),
        "p50Ms": p50,
        "p99Ms": p99,
        "minMs": round(ordered[0], 1),
        "maxMs": round(ordered[-1], 1),
        "tail": "rough: under 100 samples" if len(ordered) < 100 else "ok",
        "latency": {"p50Ms": p50, "p99Ms": p99},
    }


def _check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ToolError(
            "measure_latency takes an http(s) URL with a host, e.g. https://registry.npmjs.org/react"
        )
    if parts.username or parts.password:
        raise ToolError("Don't put credentials in the URL: measure only public endpoints.")


def _counts(statuses: dict[str, int]) -> str:
    return ", ".join(f"{n}× {status}" for status, n in statuses.items()) or "no responses"


@server.prompt(
    title="Model my codebase in Amber",
    description="Read the current codebase, turn its architecture into an Amber design, and test it against "
    "a traffic, latency, and cost target.",
)
def model_codebase(target: str = "the traffic it expects, with p99 under 500 ms") -> str:
    return f"""Model this codebase's architecture in Amber and check whether it meets: {target}.

1. Read the code, not just the README: entry points and routes, outbound HTTP clients, database and cache
   clients, queues, LLM SDK calls (OpenAI, Anthropic, Groq, ...), agent or tool loops, and deploy config
   (Dockerfile, compose, k8s, Terraform) for replica counts, pool sizes, and timeouts.
2. Map each runtime component to an Amber node: a web server or worker is a service (replicas and worker
   concurrency from the deploy config), Postgres/MySQL/Mongo is a database (connectionPool from the
   client's pool size), Redis/Memcached in front of a lookup is a cache, a call to a hosted model API is an
   llm in "hosted" mode (pick the closest presetId from get_presets), and a loop of LLM calls with tools is
   an agent with a role "llm" edge to that llm. A single LLM call goes through an agent node too (1 call,
   0 tools), so its prompt and output token sizes match what the code sends (e.g. max_tokens). Each
   endpoint with its own path gets its own users node (its share of the traffic) and service node, in
   one design. Edges follow who calls whom.
   Python workers: count processes (gunicorn/uvicorn workers) as replicas, 1 concurrency each if CPU-bound.
3. Measure before you assume. For every public endpoint the code calls (package registries, public APIs,
   object storage, and the app's own deployed read-only routes if its URL is in the code or config), run
   measure_latency on a representative GET URL and put its `latency` on the node that stands for that
   call. Never measure endpoints that need an API key or that create, change or delete anything. Each
   sample includes this machine's internet trip, so for calls between servers in one cloud region treat
   the result as an upper bound and say so.
   Where nothing can be measured (internal work, database queries, cache hit rates, calls per agent run),
   pick a sensible value. Keep a table of every latency and whether it was measured (with its URL and
   sample count) or assumed, and report "N of M latencies measured".
4. Start from the closest list_templates design, validate_design until it is clean, then simulate.
5. Report p50/p99, error rate, monthly cost, and the bottlenecks, each tied back to the file or setting
   it comes from. If a node is over 80% busy, say its p99 is sensitive to the latencies you assumed.
   If the target is missed, change capacity (replicas, pools, cache, batch sizes), simulate again, and
   say which change in the codebase or deploy config each fix corresponds to.
6. Include the measured-vs-assumed table, then end with the open_url of the final design so the user can
   see it in Amber's editor."""


def open_url(design: object) -> str:
    """A link to Amber's editor with the design in its #d= fragment (raw deflate, then base64url).
    frontend/src/lib/designFile.ts reads this format; keep the two in step. A fragment never reaches the
    server, so the design stays between the agent, the user, and their browser."""
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)  # -15: raw deflate, no zlib header
    packed = packer.compress(json.dumps(design, separators=(",", ":")).encode()) + packer.flush()
    return f"{API_URL}/#d={base64.urlsafe_b64encode(packed).decode().rstrip('=')}"


async def _call(method: str, path: str, body: dict | None = None) -> object:
    """One API request. Every failure becomes a ToolError the agent can read and act on."""
    try:
        async with httpx.AsyncClient(base_url=API_URL, timeout=TIMEOUT_S) as client:
            response = await client.request(method, path, json=body)
    except httpx.HTTPError as e:
        raise ToolError(
            f"Couldn't reach the Amber API at {API_URL} ({type(e).__name__}). "
            "Check AMBER_API_URL, or try again: the live app can take a few seconds to wake up."
        ) from None
    if response.status_code == 422:
        lines = [_issue_line(i) for i in response.json()["issues"]]
        raise ToolError("The design can't run. Fix these and try again:\n" + "\n".join(lines))
    if response.is_error:
        raise ToolError(_error_line(response))
    return response.json()


def _design(design: dict | str) -> object:
    """The design as JSON, with a placeholder position on any node that has none (the API requires one,
    but only the canvas uses it). Agents often send the design as a string, so that's accepted too."""
    if isinstance(design, str):
        try:
            design = json.loads(design)
        except json.JSONDecodeError as e:
            raise ToolError(f"The design isn't valid JSON: {e}") from None
    if not isinstance(design, dict) or not isinstance(design.get("nodes"), list):
        return design  # the API reports what's wrong with it
    nodes = [{"position": {"x": 0, "y": 0}, **n} if isinstance(n, dict) else n for n in design["nodes"]]
    return {**design, "nodes": nodes}


def _issue_line(issue: dict) -> str:
    where = ", ".join(f"{key} {issue[key]}" for key in ("nodeId", "edgeId", "path") if issue.get(key))
    return f"- {issue['code']}{f' ({where})' if where else ''}: {issue['message']}"


def _error_line(response: httpx.Response) -> str:
    try:
        body = response.json()
        text = f"{body['error']}: {body['detail']}"
    except (ValueError, KeyError, TypeError):
        text = response.text[:200] or response.reason_phrase
    if retry := response.headers.get("Retry-After"):
        text += f" Retry after {retry} s."
    return f"Amber API error {response.status_code}. {text}"


def _without(d: dict, *keys: str) -> dict:
    return {k: v for k, v in d.items() if k not in keys}


def main() -> None:
    server.run()  # stdio


if __name__ == "__main__":
    main()
