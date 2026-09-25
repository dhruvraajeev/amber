# Changelog

## v1.0.0 — 2026-09-25

The first release: a complete architecture simulator you can use in the browser, from a terminal, or
from an AI agent. Live at <https://amber.victoriousrock-f5544b42.westus.azurecontainerapps.io>.

### Simulator
- A discrete-event engine written from scratch (generator processes, FIFO resources, a
  deterministic event heap). The same design, config, and seed always give byte-identical results.
- Seven node kinds: users (constant, ramp, and spike traffic), load balancer (round robin, least
  connections), service (replicas × worker slots with bounded queues), cache, database (connection
  pools), agent (a loop of LLM and tool calls with a growing context), and LLM.
- Hosted LLMs: time to first token, token streaming speed, a rate limit with exponential backoff
  and retries, and per-token cost.
- Self-hosted LLMs: continuous batching per GPU replica, KV-cache admission, prefill/decode timing,
  and speculative decoding.
- Results: latency percentiles, time to first token, throughput, errors, per-node utilization and
  queues, GPU KV-cache series, where the slowest 1% of requests spend their time, monthly cost, and
  plain-English findings.
- Verified against queueing theory: M/M/1 and M/M/c agree within 1% over 100 runs each.

### Editor
- A canvas with a node palette, per-kind inspector forms, presets for GPUs, models, hosted LLMs,
  databases, and services, and validation as you edit.
- Three templates: a classic web app, a RAG chatbot on a hosted LLM, and a tool-using agent on a
  self-hosted GPU.
- Run, then replay the timeline on the canvas; a results drawer with charts, bottlenecks, cost, and
  attribution; Compare for two pinned runs; autosave.
- Open and export designs as JSON files, and open `#d=` links carrying a design, laid out
  automatically.

### MCP server
- `amber-mcp` (stdio) with four tools (`list_templates`, `get_presets`, `validate_design`,
  `simulate`) and a `model_codebase` prompt that turns the repository an agent is working in into an
  Amber design.
- `simulate` returns an `open_url` that opens the agent's design in the editor. Nothing is stored:
  the design travels in the link's fragment.
- Install for Claude Code, Cursor, or Claude Desktop with one `uvx` command. See the README.

### API and delivery
- FastAPI: `/api/templates`, `/api/presets`, `/api/validate`, `/api/simulate`, and `/healthz`
  (which reports the running commit). Guardrails: body size, per-IP rate limit, two runs at once,
  and a 20 s wall-time cap per run.
- Contracts are shared: Pydantic → OpenAPI → generated TypeScript, with drift failing CI.
- One multi-arch Docker image (`ghcr.io/dhruvraajeev/amber`), deployed to Azure Container Apps that
  scale to zero, at $0.

### Known limits
- The LLM serving model is not calibrated yet (one uncalibrated GPU timing profile; preset prices
  marked "verify"). Calibration against real hardware comes in v1.1.
- See the README's Limitations for the modeling simplifications.
