"""Security headers on every response, and the API docs only in dev (plan §18, 28.5c)."""

import pytest
from fastapi.testclient import TestClient

from amber.api.app import SECURITY_HEADERS, create_app
from amber.api.openapi import schema


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("GET", "/", None),  # the SPA when built, a 404 when not: headers either way
        ("GET", "/api/presets", 200),
        ("POST", "/api/simulate", 422),
        ("GET", "/nope.js", 404),
    ],
)
def test_every_response_has_the_security_headers(client, method, path, status):
    r = client.request(method, path, json={} if method == "POST" else None)
    if status:
        assert r.status_code == status
    for name, value in SECURITY_HEADERS.items():
        assert r.headers[name] == value


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_are_off_in_production_and_on_in_dev(monkeypatch, path):
    monkeypatch.delenv("AMBER_ENV", raising=False)
    with TestClient(create_app()) as prod:
        assert prod.get(path).status_code == 404
    monkeypatch.setenv("AMBER_ENV", "dev")
    with TestClient(create_app()) as dev:
        assert dev.get(path).status_code == 200


def test_the_schema_export_still_works_with_docs_off():
    assert "/api/simulate" in schema()["paths"]
