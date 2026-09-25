"""The read-only endpoints (plan §9): health, presets and templates. All cached; none touch the simulator."""

import os
from importlib.metadata import version

from fastapi import APIRouter

from amber.contracts import Design
from amber.presets import all_presets, templates

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness, and which commit is running: the published image carries its git sha (AMBER_SHA), so a
    redeploy can be confirmed from outside. `async` so it answers even while simulations fill the threads."""
    return {"status": "ok", "version": version("amber"), "sha": os.environ.get("AMBER_SHA", "dev")}


@router.get("/api/presets")
async def get_presets() -> dict[str, list]:
    """Every preset in shared/presets, plus the calibration profiles."""
    return all_presets()


@router.get("/api/templates", response_model=list[Design], response_model_exclude_none=True)
async def get_templates() -> tuple[Design, ...]:
    """The starter designs, exactly as the files in shared/templates have them."""
    return templates()
