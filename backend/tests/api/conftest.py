import json

import pytest
from fastapi.testclient import TestClient

from amber.api.app import create_app
from amber.presets import SHARED


@pytest.fixture
def client():
    """A fresh app per test, so one test's rate-limit permits never leak into the next."""
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def templates() -> dict[str, dict]:
    """The shared templates as raw JSON, by file stem."""
    return {p.stem: json.loads(p.read_text()) for p in (SHARED / "templates").glob("*.json")}
