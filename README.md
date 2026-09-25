# Amber

A flight simulator for AI app architectures: sketch a system on a canvas, drive traffic through it,
and see where latency, GPU memory, and cost break — before you build it.

> Work in progress: the demo and architecture docs arrive with v1.0.0.

## Quickstart

With [Docker](https://docs.docker.com/get-started/get-docker/), one image serves the UI and the API:

```bash
docker build -t amber .
docker run --rm -p 8000:8000 amber
```

Open <http://localhost:8000> and pick a template.

### Develop

Needs [uv](https://docs.astral.sh/uv/) and Node 24. Two terminals:

```bash
cd backend && uv sync && uv run uvicorn amber.api.app:app --reload
cd frontend && npm ci && npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to the backend on :8000.

### Test

```bash
cd backend && uv run pytest && uv run ruff check .
cd frontend && npm test && npx tsc -b && npm run lint
cd mcp && uv run pytest && uv run ruff check .
```

Simulate a design without the UI:

```bash
cd backend && uv run python -m amber.cli ../shared/templates/classic-web-app.json --duration 60 --seed 1
```

After changing a backend contract, run `npm run gen:types` in `frontend/`. CI fails if you forget.

## Use it from an AI agent (MCP)

`mcp/` is an [MCP](https://modelcontextprotocol.io) server, so Claude Code, Cursor, or any MCP client can
design and test systems with Amber. It has four tools:

| Tool | What it does |
|---|---|
| `list_templates` | The starter designs, ready to copy and change |
| `get_presets` | The GPU, model, hosted-LLM, database, and service presets a design can name |
| `validate_design` | Checks a design and lists every problem |
| `simulate` | Runs a design and returns latency percentiles, errors, bottlenecks, and monthly cost |

The tools call the live Amber API, and nothing is installed but the server. Set `AMBER_API_URL` to use
another one, such as `http://localhost:8000` for a local backend. The live API allows 30 simulations a minute
per address.

**Claude Code:**

```bash
claude mcp add amber -- uvx --from "git+https://github.com/dhruvraajeev/amber#subdirectory=mcp" amber-mcp
```

Add `-e AMBER_API_URL=http://localhost:8000` before the `--` for a local backend. `-s user` makes it
available in every project.

**Cursor** (`~/.cursor/mcp.json`, or `.cursor/mcp.json` in a project):

```json
{
  "mcpServers": {
    "amber": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/dhruvraajeev/amber#subdirectory=mcp", "amber-mcp"]
    }
  }
}
```

To install the command once instead of fetching it with `uvx`, run
`uv tool install "git+https://github.com/dhruvraajeev/amber#subdirectory=mcp"`, then configure `amber-mcp` as
the command.

Then ask, for example: *"Using the Amber tools, design an API for 400 requests/second with p99 under 150 ms
for less than $600 a month."*

## License

MIT — see [LICENSE](LICENSE).
