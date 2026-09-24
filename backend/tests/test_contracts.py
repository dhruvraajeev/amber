"""The Pydantic contracts must read and write exactly the JSON the frontend does (plan §7)."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from amber.contracts import Design, RunConfig, RunResult
from amber.presets import SHARED

TEMPLATES = sorted((SHARED / "templates").glob("*.json"))
FIXTURES = sorted((SHARED / "fixtures" / "graph").glob("*.json"))


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def template(stem: str) -> dict:
    return load(SHARED / "templates" / f"{stem}.json")


def node(design: dict, kind: str) -> dict:
    return next(n for n in design["nodes"] if n["kind"] == kind)


def as_json(model) -> dict:
    return model.model_dump(mode="json", exclude_none=True)


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.stem)
def test_template_round_trips(path):
    raw = load(path)
    assert as_json(Design.model_validate(raw)) == raw


def test_python_fields_are_snake_case_json_is_camel_case():
    design = Design.model_validate(template("classic-web-app"))
    assert design.nodes[0].params.client_timeout_ms == 5000
    assert "clientTimeoutMs" in as_json(design)["nodes"][0]["params"]
    # Python code can also build models by field name.
    assert RunConfig(duration_s=60, seed=1).warmup_s == 5


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_graph_fixtures_parse_unless_they_break_a_field_range(path):
    """Structural problems (cycles, bad edges, limits) are graph.py's job, so those designs still parse."""
    fixture = load(path)
    if "PARAM_RANGE" in fixture["expect"]:
        with pytest.raises(ValidationError):
            Design.model_validate(fixture["design"])
    else:
        Design.model_validate(fixture["design"])
    if "LIMIT_DURATION" in fixture["expect"]:
        with pytest.raises(ValidationError):
            RunConfig.model_validate(fixture["config"])
    else:
        RunConfig.model_validate(fixture["config"])


# (template stem, node kind, params key path, bad value): each must be rejected.
OUT_OF_RANGE = [
    ("classic-web-app", "service", "replicas", 0),
    ("classic-web-app", "service", "replicas", 51),
    ("classic-web-app", "service", "replicas", 2.5),
    ("classic-web-app", "service", "concurrencyPerReplica", 1001),
    ("classic-web-app", "service", "queueLimit", -1),
    ("classic-web-app", "service", "costPerReplicaMonth", -1),
    ("classic-web-app", "service", "work.p99Ms", 1),
    ("classic-web-app", "service", "work.p50Ms", 0),
    ("classic-web-app", "service", "work.p50Ms", float("nan")),
    ("classic-web-app", "cache", "hitRate", 1.5),
    ("classic-web-app", "database", "connectionPool", 0),
    ("classic-web-app", "database", "preset", "oracle"),
    ("classic-web-app", "users", "clientTimeoutMs", 0),
    ("classic-web-app", "users", "traffic.rps", -5),
    ("classic-web-app", "users", "traffic.type", "burst"),
    ("classic-web-app", "loadBalancer", "algorithm", "random"),
    ("agent-self-hosted", "agent", "llmCallsMean", 0.5),
    ("agent-self-hosted", "agent", "outputTokensPerCall", 0),
    ("agent-self-hosted", "llm", "replicas", 51),
    ("agent-self-hosted", "llm", "profileId", ""),
    ("agent-self-hosted", "llm", "mode", "cloud"),
]


def set_path(params: dict, path: str, value) -> None:
    *parents, last = path.split(".")
    for key in parents:
        params = params[key]
    params[last] = value


@pytest.mark.parametrize(("stem", "kind", "path", "value"), OUT_OF_RANGE)
def test_out_of_range_params_are_rejected(stem, kind, path, value):
    design = template(stem)
    set_path(node(design, kind)["params"], path, value)
    with pytest.raises(ValidationError):
        Design.model_validate(design)


def test_unknown_keys_are_rejected():
    design = template("classic-web-app")
    node(design, "service")["params"]["work"]["p50"] = 15  # a typo'd copy of p50Ms
    with pytest.raises(ValidationError):
        Design.model_validate(design)


def test_speculative_fields_are_checked_only_when_enabled():
    design = template("agent-self-hosted")
    spec = node(design, "llm")["params"]["speculative"]
    spec.update(enabled=False, draftTokens=0, acceptanceRate=2)
    Design.model_validate(design)
    spec["enabled"] = True
    with pytest.raises(ValidationError):
        Design.model_validate(design)


def test_hosted_tokens_per_second_needs_a_slow_tail_below_the_median():
    design = template("rag-chatbot-hosted")
    tps = node(design, "llm")["params"]["tokensPerSecond"]
    Design.model_validate(design)
    tps["p99Low"] = tps["p50"] + 1
    with pytest.raises(ValidationError):
        Design.model_validate(design)


@pytest.mark.parametrize("duration", [9, 601])
def test_run_duration_is_ten_to_six_hundred_seconds(duration):
    with pytest.raises(ValidationError):
        RunConfig.model_validate({"durationS": duration, "seed": 1, "warmupS": 5})


RESULT = {
    "designHash": "ab" * 32,
    "config": {"durationS": 60, "seed": 42, "warmupS": 5},
    "engine": {"events": 1000, "wallMs": 12.5, "eventsPerSec": 80000, "simulatedRequests": 120},
    "summary": {
        "requests": 120,
        "completed": 118,
        "errors": 2,
        "timeouts": 0,
        "rejected": 2,
        "throughputRps": 1.97,
        "errorRate": 0.0167,
        "latencyMs": {"p50": 20, "p95": 55, "p99": 80, "max": 120},
    },
    "timeline": [
        {
            "t": 0,
            "arrivalsRps": 2,
            "throughputRps": 2,
            "errorRate": 0,
            "p50": 20,
            "p95": 50,
            "p99": 70,
            "nodes": {"n_api": {"util": 0.4, "queue": 0, "rejects": 0, "throughputRps": 2}},
        }
    ],
    "nodes": [
        {
            "id": "n_api",
            "kind": "service",
            "utilAvg": 0.4,
            "utilMax": 0.6,
            "queueAvg": 0,
            "queueMax": 1,
            "rejects": 2,
            "monthlyUsd": 120,
        }
    ],
    "gpu": [{"nodeId": "n_llm", "points": [{"t": 0, "kvPct": 0.5, "batch": 8, "waiting": 1}]}],
    "attribution": [{"nodeId": "n_api", "queueShare": 0.25, "workShare": 0.75}],
    "cost": {
        "monthlyTotalUsd": 120,
        "breakdown": [{"nodeId": "n_api", "usd": 120, "detail": "4 × $30/replica"}],
        "assumptions": ["Traffic repeats all month."],
    },
    "bottlenecks": [{"severity": "info", "message": "No bottlenecks at this traffic. p99 is 80 ms."}],
}


def test_run_result_round_trips():
    assert as_json(RunResult.model_validate(RESULT)) == RESULT


def test_run_result_optional_fields_round_trip():
    raw = copy.deepcopy(RESULT)
    raw["runId"] = "r_1"
    raw["summary"]["ttftMs"] = {"p50": 300, "p95": 700, "p99": 900}
    raw["bottlenecks"][0]["nodeId"] = "n_api"
    assert as_json(RunResult.model_validate(raw)) == raw
