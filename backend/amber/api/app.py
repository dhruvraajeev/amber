"""Amber's HTTP API (plan §9). Locally: `uv run uvicorn amber.api.app:app --reload` (port 8000,
where the Vite dev server's `/api` proxy points)."""

import asyncio
import os
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.types import Scope

from amber.api import errors, routes_meta, routes_sim
from amber.api.limits import MAX_CONCURRENT_SIMULATIONS, SIMULATIONS_PER_MINUTE, RateLimiter

# The Vite dev and preview servers. Only needed when a page calls :8000 directly instead of via the proxy.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173"]

# `npm run build` output. The Docker image puts it here too; in dev, Vite serves the UI instead.
FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


class SpaFiles(StaticFiles):
    """The built UI. A page path with no file behind it gets index.html, so the router can draw `/compare`
    on a refresh. Missing files (`/assets/old.js`) and unknown `/api/…` paths stay a JSON 404: a web page
    in their place would only fail later, and more confusingly."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code != 404 or Path(path).suffix:
                raise
            return await super().get_response("index.html", scope)


def create_app(spa_dir: Path = FRONTEND_DIST) -> FastAPI:
    """A new app with its own rate limiter and simulation slots. Tests build one each; uvicorn runs `app`.
    Serves the UI from `spa_dir` when it has been built."""
    app = FastAPI(title="Amber", version=version("amber"))
    errors.install(app)
    app.include_router(routes_meta.router)
    app.include_router(routes_sim.router)
    app.state.limiter = RateLimiter(SIMULATIONS_PER_MINUTE)
    app.state.simulations = asyncio.Semaphore(MAX_CONCURRENT_SIMULATIONS)
    if os.environ.get("AMBER_ENV") == "dev":  # production serves the SPA from this origin, below
        app.add_middleware(
            CORSMiddleware, allow_origins=DEV_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"]
        )
    if (spa_dir / "index.html").is_file():
        # The router's fallback, not a mount at "/": a mount matches every path and would turn
        # `GET /api/simulate` (POST only) into a 404 instead of a 405.
        app.router.default = SpaFiles(directory=spa_dir)
    return app


app = create_app()
