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
```

Simulate a design without the UI:

```bash
cd backend && uv run python -m amber.cli ../shared/templates/classic-web-app.json --duration 60 --seed 1
```

After changing a backend contract, run `npm run gen:types` in `frontend/`. CI fails if you forget.

## License

MIT — see [LICENSE](LICENSE).
