"""The four tools against a mocked API (respx): what each one sends, what it trims, and how failures read."""

import base64
import json
import zlib

import httpx
import pytest
import respx
from mcp.server.mcpserver.exceptions import ToolError

from amber_mcp import server
from amber_mcp.server import API_URL, get_presets, list_templates, open_url, simulate, validate_design

pytestmark = pytest.mark.anyio  # anyio ships with mcp; its pytest plugin runs the async tests


@pytest.fixture
def anyio_backend():
    return "asyncio"


DESIGN = {
    "name": "Tiny",
    "version": 1,
    "nodes": [{"id": "u", "kind": "users", "label": "Users", "params": {}}],
    "edges": [],
}


@pytest.fixture
def api():
    with respx.mock(base_url=API_URL, assert_all_called=True) as mock:
        yield mock


def sent(route: respx.Route) -> dict:
    return json.loads(route.calls.last.request.content)


async def test_list_templates_drops_positions(api):
    node = {"id": "u", "kind": "users", "label": "Users", "position": {"x": 1, "y": 2}, "params": {}}
    api.get("/api/templates").respond(json=[{**DESIGN, "nodes": [node]}])
    [template] = await list_templates()
    assert template["name"] == "Tiny"
    assert "position" not in template["nodes"][0]


async def test_get_presets_drops_notes(api):
    gpu = {"id": "t4", "name": "T4", "usdPerHour": 0.53, "note": "source", "verifiedAt": "2026-09-24"}
    api.get("/api/presets").respond(json={"gpus": [gpu]})
    assert await get_presets() == {"gpus": [{"id": "t4", "name": "T4", "usdPerHour": 0.53}]}


async def test_validate_fills_positions_and_accepts_a_string(api):
    route = api.post("/api/validate").respond(json={"issues": []})
    assert await validate_design(json.dumps(DESIGN)) == {"valid": True, "issues": []}
    assert sent(route)["design"]["nodes"][0]["position"] == {"x": 0, "y": 0}


async def test_validate_returns_issues(api):
    issue = {"code": "NO_USERS", "message": "Add a users node."}
    api.post("/api/validate").respond(json={"issues": [issue]})
    assert await validate_design(DESIGN) == {"valid": False, "issues": [issue]}


async def test_simulate_sends_config_and_trims_the_result(api):
    result = {"summary": {"requests": 10}, "bottlenecks": [], "cost": {"monthlyTotalUsd": 5}}
    route = api.post("/api/simulate").respond(json={**result, "timeline": [{}] * 300, "nodes": [], "gpu": []})
    out = await simulate(DESIGN, duration_s=30, seed=7)
    assert {k: out[k] for k in result} == result and set(out) == {*result, "open_url"}
    assert sent(route)["config"] == {"durationS": 30, "seed": 7}


def test_open_url_carries_the_design():
    url = open_url(DESIGN)
    base, fragment = url.split("/#d=")
    assert base == API_URL
    packed = base64.urlsafe_b64decode(fragment + "=" * (-len(fragment) % 4))
    assert json.loads(zlib.decompress(packed, -15)) == DESIGN


async def test_simulate_422_lists_the_issues(api):
    issues = [
        {"code": "CACHE_EDGES", "message": "A cache needs one outgoing edge.", "nodeId": "c"},
        {"code": "PARAM_RANGE", "message": "p99 must be >= p50.", "nodeId": "api", "path": "work.p99Ms"},
    ]
    api.post("/api/simulate").respond(422, json={"issues": issues})
    with pytest.raises(ToolError) as e:
        await simulate(DESIGN)
    assert "- CACHE_EDGES (nodeId c): A cache needs one outgoing edge." in str(e.value)
    assert "- PARAM_RANGE (nodeId api, path work.p99Ms): p99 must be >= p50." in str(e.value)


async def test_rate_limit_says_when_to_retry(api):
    body = {"error": "rate_limited", "detail": "Too many simulations."}
    api.post("/api/simulate").respond(429, json=body, headers={"Retry-After": "2"})
    with pytest.raises(ToolError, match=r"429\. rate_limited: Too many simulations\. Retry after 2 s\."):
        await simulate(DESIGN)


async def test_unreachable_api_is_a_clear_error(api):
    api.get("/api/templates").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ToolError, match="Couldn't reach the Amber API"):
        await list_templates()


async def test_bad_json_string_is_a_clear_error():
    with pytest.raises(ToolError, match="isn't valid JSON"):
        await validate_design("{nope")


async def test_all_four_tools_are_registered():
    tools = {t.name: t for t in await server.server.list_tools()}
    assert set(tools) == {"list_templates", "get_presets", "validate_design", "simulate"}
    assert '"kind": "users"' in tools["simulate"].description  # the example rides with the tool


async def test_model_codebase_prompt_takes_the_target():
    [prompt] = await server.server.list_prompts()
    assert prompt.name == "model_codebase"
    result = await server.server.get_prompt("model_codebase", {"target": "400 rps under $600/mo"})
    assert "400 rps under $600/mo" in result.messages[0].content.text
