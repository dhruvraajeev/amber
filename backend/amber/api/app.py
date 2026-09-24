"""Amber's HTTP API (plan §9). Locally: `uv run uvicorn amber.api.app:app --reload` (port 8000,
where the Vite dev server's `/api` proxy points)."""

import asyncio
import os
from importlib.metadata import version

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from amber.api import errors, routes_meta, routes_sim
from amber.api.limits import MAX_CONCURRENT_SIMULATIONS, SIMULATIONS_PER_MINUTE, RateLimiter

# The Vite dev and preview servers. Only needed when a page calls :8000 directly instead of via the proxy.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173"]


def create_app() -> FastAPI:
    """A new app with its own rate limiter and simulation slots. Tests build one each; uvicorn runs `app`."""
    app = FastAPI(title="Amber", version=version("amber"))
    errors.install(app)
    app.include_router(routes_meta.router)
    app.include_router(routes_sim.router)
    app.state.limiter = RateLimiter(SIMULATIONS_PER_MINUTE)
    app.state.simulations = asyncio.Semaphore(MAX_CONCURRENT_SIMULATIONS)
    if os.environ.get("AMBER_ENV") == "dev":  # production serves the SPA from this origin (Step 19)
        app.add_middleware(
            CORSMiddleware, allow_origins=DEV_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"]
        )
    return app


app = create_app()
