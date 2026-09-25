"""Amber's MCP server (plan §13): lets an AI agent list templates, check a design, and run it.

Every tool is a thin wrapper over Amber's public REST API; nothing here simulates. `AMBER_API_URL` picks
the API (default: the live deploy). Run with `amber-mcp`, which speaks MCP over stdio.
"""

import json
import logging
import os

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

API_URL = os.environ.get(
    "AMBER_API_URL", "https://amber.victoriousrock-f5544b42.westus.azurecontainerapps.io"
).rstrip("/")
logging.getLogger("httpx").setLevel(logging.WARNING)  # not a log line per request on the client's stderr
TIMEOUT_S = 60  # a run may take 20 s, plus waiting for a turn, plus a cold start from zero replicas

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
- llm, self-hosted: mode "selfHosted", gpuPresetId, modelPresetId, profileId ("default"), replicas,
  maxBatchSize, maxBatchTokens, maxOutputTokensReserve,
  speculative {"enabled","draftTokens","acceptanceRate","draftStepMs"}.
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
    """The preset ids a design can name: gpus and models (for self-hosted llm nodes), hostedLlms (for hosted
    llm nodes), databases and services (typical params). Prices are estimates."""
    presets = await _call("GET", "/api/presets")
    return {kind: [_without(p, "note", "verifiedAt") for p in items] for kind, items in presets.items()}


@server.tool(description="Checks a design without running it and returns every problem.\n" + DESIGN_GUIDE)
async def validate_design(design: dict | str) -> dict:
    issues = (await _call("POST", "/api/validate", {"design": _design(design)}))["issues"]
    return {"valid": not issues, "issues": issues}


@server.tool(
    description="Runs a design for duration_s simulated seconds (10-600) and returns the summary (latency "
    "percentiles, throughput, errors), the bottlenecks found, and the monthly cost. The same design and seed "
    "always give the same result.\n" + DESIGN_GUIDE
)
async def simulate(design: dict | str, duration_s: float = 60, seed: int = 42) -> dict:
    body = {"design": _design(design), "config": {"durationS": duration_s, "seed": seed}}
    result = await _call("POST", "/api/simulate", body)
    return {key: result[key] for key in ("summary", "bottlenecks", "cost")}  # never the timeline: too big


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
