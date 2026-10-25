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

# Sent on every response. Scripts, fonts and API calls come from this origin only. Styles also allow inline:
# React and React Flow set element styles, and the UI has no innerHTML or eval for an injected style to ride.
# `data:` images are the select arrow in theme.css.
SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; "
    "form-action 'self'",
}


class SpaFiles(StaticFiles):
    """The built UI. A page path with no file behind it gets index.html, so the router can draw `/compare`
    on a refresh. Missing files (`/assets/old.js`), unknown `/api/…` paths and the docs pages that production
    turns off stay a JSON 404: a web page in their place would only fail later, and more confusingly."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path.split("/")[0] in ("api", "docs", "redoc"):
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
    dev = os.environ.get("AMBER_ENV") == "dev"
    # The docs pages and /openapi.json only in dev. `app.openapi()` still builds the schema either way,
    # which is all `python -m amber.api.openapi` needs.
    docs = {} if dev else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="Amber", version=version("amber"), **docs)
    errors.install(app)
    app.include_router(routes_meta.router)
    app.include_router(routes_sim.router)
    app.state.limiter = RateLimiter(SIMULATIONS_PER_MINUTE)
    app.state.simulations = asyncio.Semaphore(MAX_CONCURRENT_SIMULATIONS)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    if dev:  # production serves the SPA from this origin, below
        app.add_middleware(
            CORSMiddleware, allow_origins=DEV_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"]
        )
    if (spa_dir / "index.html").is_file():
        # The router's fallback, not a mount at "/": a mount matches every path and would turn
        # `GET /api/simulate` (POST only) into a 404 instead of a 405.
        app.router.default = SpaFiles(directory=spa_dir)
    return app


app = create_app()
