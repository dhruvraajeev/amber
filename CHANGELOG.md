# Changelog

## v1.0.1 — 2026-09-25

Post-release fixes. No new features.

### Fixed
- **Hosted LLM cost was too low on short runs.** A call was billed only when it finished, so calls still
  streaming when the run ended were dropped, and the empty first seconds of a run were averaged in. A
  60 s run reported the RAG template's LLM bill 7% low (13% at 30 s). Calls are now billed when admitted,
  from the end of warmup, and the monthly figure scales from the time after warmup. Measured against the
  exact formula over 400 runs, it is now within 2.5% at 30 s and within 1% at 60 s.
- The Users node showed 0 req/s during replay and in per-node data; it now shows what it sends.
- The MCP server reported an empty version to clients; it now reports its package version.
- The architecture diagram in `docs/architecture.md` failed to render on GitHub (a reserved word as a
  node id).

### Changed
- The MCP design guide and `model_codebase` prompt tell agents three things that decide accuracy on a real
  codebase: count Python worker processes, not threads, as parallel capacity; use latencies measured
  under load; and warn that p99 is fragile when anything is over 80% busy.
- README rewritten in plain language: screenshots, a glossary, two diagrams, and measured accuracy,
  including Amber predicting its own API under real load.

### Removed
- The frontend's unused copy of the design hash (the backend sends it in every result).
- The `/share/:token` placeholder page (share links come with v1.2).
- The always-empty `profiles` list in `GET /api/presets` (it returns when calibration adds profiles).

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
