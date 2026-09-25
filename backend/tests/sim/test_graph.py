"""The backend validator gives the same answers as frontend/src/lib/validate.ts (plan §7.6, §3)."""

import copy
import json
from pathlib import Path

import pytest

from amber.presets import SHARED
from amber.sim.graph import validate

FIXTURES = sorted((SHARED / "fixtures" / "graph").glob("*.json"))
TEMPLATES = sorted((SHARED / "templates").glob("*.json"))
CONFIG = {"durationS": 60, "seed": 42, "warmupS": 5}


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def valid_design() -> dict:
    return load(SHARED / "fixtures" / "graph" / "valid.json")["design"]


def node(design: dict, kind: str) -> dict:
    return next(n for n in design["nodes"] if n["kind"] == kind)


def codes(design, config=None) -> list[str]:
    return sorted({i.code for i in validate(design, config)})


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_shared_fixture_gives_the_same_codes_as_the_frontend(path):
    fixture = load(path)
    assert codes(fixture["design"], fixture["config"]) == fixture["expect"]


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.stem)
def test_templates_are_valid(path):
    assert validate(load(path), CONFIG) == []


def test_range_errors_and_structural_errors_are_reported_together():
    design = valid_design()
    node(design, "service")["params"]["replicas"] = 0
    node(design, "database")["params"]["connectionPool"] = 0  # a second range error
    design["edges"].append(
        {"id": "loop", "source": node(design, "database")["id"], "target": design["nodes"][1]["id"]}
    )
    assert codes(design) == ["CYCLE", "LEAF_HAS_OUTGOING", "PARAM_RANGE"]


def test_users_node_with_an_incoming_edge():
    """The users-edges fixture only covers fan-out; §7.6 also forbids incoming edges."""
    design = valid_design()
    design["edges"].append(
        {"id": "in", "source": node(design, "service")["id"], "target": node(design, "users")["id"]}
    )
    assert "USERS_EDGES" in codes(design)


def test_agent_llm_edge_must_point_at_an_llm_node():
    design = valid_design()
    llm_edge = next(e for e in design["edges"] if e.get("role") == "llm")
    llm_edge["target"] = node(design, "database")["id"]
    assert "AGENT_EDGES" in codes(design)


def test_param_range_names_the_node_and_the_json_path():
    design = valid_design()
    service = node(design, "service")
    service["params"]["work"]["p99Ms"] = 1
    service["params"]["replicas"] = 51
    issues = validate(design)
    assert {(i.node_id, i.path) for i in issues} == {
        (service["id"], "params.work"),
        (service["id"], "params.replicas"),
    }
    assert all(i.message.startswith(f"{service['label']}: ") for i in issues)


def test_json_paths_drop_the_union_tags_pydantic_adds():
    """Pydantic says `params.traffic.constant.rps` and `params.hosted.ttft`; the JSON has neither tag."""
    design = valid_design()
    node(design, "users")["params"]["traffic"]["rps"] = -1
    llm = node(design, "llm")["params"]
    llm["ttft"]["p50Ms"] = 0
    del llm["maxRetries"]  # a missing field keeps its own name in the path
    assert sorted(i.path for i in validate(design)) == [
        "params.maxRetries",
        "params.traffic.rps",
        "params.ttft",
    ]


def test_unknown_preset_is_a_param_range_on_the_id_field():
    design = valid_design()
    node(design, "llm")["params"]["presetId"] = "no-such-model"
    [issue] = validate(design)
    assert (issue.code, issue.path) == ("PARAM_RANGE", "params.presetId")


def test_a_self_hosted_model_too_big_for_its_gpu_is_a_param_range_on_the_gpu_field():
    """Same words as the frontend (validate.test.ts), so the inspector shows one message either way."""
    design = load(SHARED / "fixtures" / "graph" / "model-does-not-fit.json")["design"]
    [issue] = validate(design)
    assert (issue.code, issue.node_id, issue.path) == ("PARAM_RANGE", "llm", "params.gpuPresetId")
    assert issue.message == (
        "LLM: the model does not fit on this GPU (16.1 GB of weights, 14.4 GB usable on the NVIDIA T4)."
    )
    node(design, "llm")["params"]["modelPresetId"] = "llama-3.1-8b-instruct-q4km"  # 4.9 GB fits
    assert validate(design) == []


def test_an_unknown_gpu_is_reported_once_not_also_as_does_not_fit():
    design = load(SHARED / "fixtures" / "graph" / "model-does-not-fit.json")["design"]
    node(design, "llm")["params"]["gpuPresetId"] = "no-such-gpu"
    assert [i.message for i in validate(design)] == ['LLM: unknown preset "no-such-gpu".']
    node(design, "llm")["params"]["gpuPresetId"] = ["not", "a", "string"]  # malformed JSON doesn't crash
    assert codes(design) == ["PARAM_RANGE"]


def test_limit_duration_points_at_the_config_field():
    [issue] = validate(valid_design(), {**CONFIG, "durationS": 5})
    assert (issue.code, issue.path) == ("LIMIT_DURATION", "config.durationS")


def test_request_limit_uses_the_given_duration_even_when_it_is_out_of_range():
    """Same as the frontend: 400 req/s for 700 s is 280k requests, so both limits are reported."""
    design = valid_design()
    node(design, "users")["params"]["traffic"] = {"type": "constant", "rps": 400}
    assert codes(design, {**CONFIG, "durationS": 700}) == ["LIMIT_DURATION", "LIMIT_REQUESTS"]


def test_request_limit_is_exact_at_the_boundary():
    design = valid_design()
    node(design, "users")["params"]["traffic"] = {"type": "constant", "rps": 2000}
    assert codes(design, {**CONFIG, "durationS": 100}) == []  # exactly 200,000
    node(design, "users")["params"]["traffic"]["rps"] = 2000.01
    assert codes(design, {**CONFIG, "durationS": 100}) == ["LIMIT_REQUESTS"]  # 200,001


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["edges"][0].pop("source"),
        lambda d: d["nodes"].append({"id": "x", "kind": "queue", "label": "x", "position": {"x": 0, "y": 0}}),
        lambda d: d.pop("nodes"),
    ],
    ids=["edge-without-source", "unknown-kind", "no-nodes"],
)
def test_json_that_is_not_a_design_is_a_schema_issue_not_a_crash(mutate):
    design = valid_design()
    node(design, "service")["params"]["replicas"] = 0  # hidden: the graph can't be trusted
    mutate(design)
    assert codes(design) == ["SCHEMA"]


def test_not_even_an_object():
    assert codes([1, 2, 3]) == ["SCHEMA"]


def test_a_chain_deeper_than_the_recursion_limit_does_not_crash():
    design = valid_design()
    service = node(design, "service")
    chain = [{**copy.deepcopy(service), "id": f"s{i}", "label": f"s{i}"} for i in range(3000)]
    design["nodes"] += chain
    design["edges"] += [{"id": f"c{i}", "source": f"s{i}", "target": f"s{i + 1}"} for i in range(2999)]
    design["edges"].append({"id": "back", "source": "s2999", "target": "s0"})
    assert {"CYCLE", "LIMIT_NODES", "LIMIT_EDGES"} <= set(codes(design))
