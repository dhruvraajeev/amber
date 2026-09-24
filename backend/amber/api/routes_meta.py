"""The read-only endpoints (plan §9): health, presets and templates. All cached; none touch the simulator."""

from importlib.metadata import version

from fastapi import APIRouter

from amber.contracts import Design
from amber.presets import all_presets, templates

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness. `async` so it is answered on the event loop, even while simulations fill the threads."""
    return {"status": "ok", "version": version("amber")}


@router.get("/api/presets")
async def get_presets() -> dict[str, list]:
    """Every preset in shared/presets, plus the calibration profiles."""
    return all_presets()


@router.get("/api/templates", response_model=list[Design], response_model_exclude_none=True)
async def get_templates() -> tuple[Design, ...]:
    """The starter designs, exactly as the files in shared/templates have them."""
    return templates()
