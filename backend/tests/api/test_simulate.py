"""The HTTP API (plan §9): what each endpoint answers, and the shape of every error."""

import json

from fastapi.testclient import TestClient

from amber.api.app import create_app
from amber.api.limits import MAX_BODY_BYTES
from amber.contracts import Design, RunConfig, RunResult
from amber.presets import SHARED
from amber.sim.run import simulate

CONFIG = {"durationS": 20, "seed": 3}


def without_wall_fields(result: dict) -> dict:
    return {
        **result,
        "engine": {k: v for k, v in result["engine"].items() if k not in {"wallMs", "eventsPerSec"}},
    }


# ── Read-only endpoints ──────────────────────────────────────────────────────


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok", "version": "0.1.0"}


def test_presets_are_the_shared_files_under_the_frontends_names(client):
    body = client.get("/api/presets").json()
    assert body.keys() == {"gpus", "models", "hostedLlms", "databases", "services", "profiles"}
    assert body["hostedLlms"] == json.loads((SHARED / "presets" / "hosted_llms.json").read_text())
    assert body["profiles"] == []  # calibration profiles arrive in Part 2


def test_templates_come_back_exactly_as_the_files_have_them(client, templates):
    # No `"id": null` or `"role": null` added: the frontend's design hash would see them.
    assert client.get("/api/templates").json() == [templates[k] for k in sorted(templates)]


# ── POST /api/validate ───────────────────────────────────────────────────────


def test_validate_answers_200_with_every_issue(client, templates):
    design = templates["classic-web-app"]
    design["edges"] = [e for e in design["edges"] if e["source"] != "n_users"]
    response = client.post("/api/validate", json={"design": design})
    assert response.status_code == 200
    assert {"code": "USERS_EDGES", "nodeId": "n_users"}.items() <= response.json()["issues"][0].items()


def test_validate_checks_run_limits_only_when_a_config_is_sent(client, templates):
    design = templates["classic-web-app"]
    assert client.post("/api/validate", json={"design": design}).json() == {"issues": []}
    issues = client.post("/api/validate", json={"design": design, "config": {"durationS": 5, "seed": 1}})
    assert [i["code"] for i in issues.json()["issues"]] == ["LIMIT_DURATION"]


# ── POST /api/simulate ───────────────────────────────────────────────────────


def test_simulate_returns_exactly_what_the_simulator_does(client, templates):
    response = client.post("/api/simulate", json={"design": templates["classic-web-app"], "config": CONFIG})
    assert response.status_code == 200
    body = response.json()
    RunResult.model_validate(body)  # a valid contract…
    direct = simulate(Design.model_validate(templates["classic-web-app"]), RunConfig.model_validate(CONFIG))
    expected = direct.model_dump(mode="json", exclude_none=True)
    assert without_wall_fields(body) == without_wall_fields(expected)  # …and the same run, number for number


def test_a_design_that_cant_run_is_a_422_listing_its_issues(client):
    empty = {"name": "empty", "version": 1, "nodes": [], "edges": []}
    response = client.post("/api/simulate", json={"design": empty, "config": CONFIG})
    assert response.status_code == 422
    assert response.json() == {
        "issues": [{"code": "NO_USERS", "message": "Add a Users node: traffic has to start somewhere."}]
    }


def test_a_missing_config_is_reported_as_issues_too(client, templates):
    response = client.post("/api/simulate", json={"design": templates["classic-web-app"]})
    assert response.status_code == 422
    assert {i["path"] for i in response.json()["issues"]} == {"config.durationS", "config.seed"}


def test_a_body_that_isnt_an_object_is_a_schema_issue(client):
    response = client.post("/api/simulate", json=[1, 2, 3])
    assert response.status_code == 422
    assert [i["code"] for i in response.json()["issues"]] == ["SCHEMA"]


def test_node_kinds_the_simulator_cant_run_yet_are_a_501(client, templates):
    response = client.post("/api/simulate", json={"design": templates["agent-self-hosted"], "config": CONFIG})
    assert response.status_code == 501
    assert response.json() == {"error": "not_implemented", "detail": "Agent nodes are not simulated yet."}


# ── Other errors: always {"error", "detail"} ─────────────────────────────────


def test_invalid_json_is_a_400(client):
    response = client.post(
        "/api/simulate", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert response.status_code == 400
    assert response.json()["error"] == "bad_json"


def test_bodies_over_256_kb_are_refused_with_or_without_a_length(client):
    too_big = b" " * (MAX_BODY_BYTES + 1)
    declared = client.post("/api/validate", content=too_big)
    chunked = client.post("/api/validate", content=iter([too_big[:1000], too_big[1000:]]))  # no length
    assert "content-length" not in chunked.request.headers
    for response in (declared, chunked):
        assert response.status_code == 413
        assert response.json()["error"] == "too_large"


def test_unknown_paths_and_methods_use_the_same_error_shape(client):
    assert client.get("/api/nope").json() == {"error": "not_found", "detail": "Not Found"}
    assert client.get("/api/simulate").json()["error"] == "method_not_allowed"


# ── CORS: dev only ───────────────────────────────────────────────────────────


def preflight(client):
    headers = {"origin": "http://localhost:5173", "access-control-request-method": "POST"}
    return client.options("/api/simulate", headers=headers)


def test_cors_is_off_unless_amber_env_is_dev(monkeypatch):
    monkeypatch.delenv("AMBER_ENV", raising=False)
    assert "access-control-allow-origin" not in preflight(TestClient(create_app())).headers
    monkeypatch.setenv("AMBER_ENV", "dev")
    allowed = preflight(TestClient(create_app())).headers["access-control-allow-origin"]
    assert allowed == "http://localhost:5173"


# ── OpenAPI ──────────────────────────────────────────────────────────────────


def test_the_test_only_hooks_stay_out_of_the_openapi_schema(client):
    schema = client.get("/openapi.json").text.lower()
    assert "sampler" not in schema and "wall_limit" not in schema and "walllimit" not in schema  # §16
