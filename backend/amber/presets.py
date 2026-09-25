"""The files in shared/ that the frontend and backend both read: presets and templates.

shared/ sits at the repo root, next to backend/, and the Dockerfile copies it to the same place.
Every file is read once and cached; they never change while the server runs.
"""

import json
from functools import cache
from pathlib import Path

from amber.contracts import Design

SHARED = Path(__file__).resolve().parents[2] / "shared"

# API key → shared/presets file, named as the frontend's `getPresets()` names them.
PRESET_FILES = {
    "gpus": "gpus",
    "models": "models",
    "hostedLlms": "hosted_llms",
    "databases": "databases",
    "services": "services",
}


@cache
def presets(preset_file: str) -> dict[str, dict]:
    """One shared/presets file as {id: preset}. Nodes read their defaults from here."""
    return {p["id"]: p for p in _read(SHARED / "presets" / f"{preset_file}.json")}


@cache
def all_presets() -> dict[str, list]:
    """Every preset list, for `GET /api/presets`."""
    return {key: list(presets(file).values()) for key, file in PRESET_FILES.items()}


@cache
def templates() -> tuple[Design, ...]:
    """The starter designs in shared/templates, in file-name order."""
    return tuple(Design.model_validate(_read(p)) for p in sorted((SHARED / "templates").glob("*.json")))


def _read(path: Path) -> object:
    return json.loads(path.read_text())
