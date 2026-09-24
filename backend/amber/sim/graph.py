"""Graph rules (plan §7.6) and limits (§3): the backend's copy of frontend/src/lib/validate.ts.

Both validators are tested against the same fixtures in shared/fixtures/graph/, so keep them in step.
`validate` takes raw JSON (dicts), not parsed models, because it must report *every* problem at once:
field ranges come from the Pydantic contracts, but a design that fails them is still checked for
cycles, bad edges and limits, exactly as the frontend does.
"""

import math

from pydantic import TypeAdapter, ValidationError

from amber.contracts import Design, RunConfig, TrafficProfile, ValidationIssue
from amber.presets import presets
from amber.sim.arrivals import expected_requests, peak
from amber.sim.nodes.llm_selfhosted import PROFILES

MAX_NODES = 50
MAX_EDGES = 100
MIN_DURATION_S, MAX_DURATION_S = 10, 600  # also enforced by RunConfig's field range
MAX_RPS = 5000
MAX_REQUESTS = 200_000

# (llm mode, params field) → the ids it may name: a shared/presets file, or the timing profiles.
PRESET_FIELDS = {
    ("hosted", "presetId"): lambda: presets("hosted_llms"),
    ("selfHosted", "gpuPresetId"): lambda: presets("gpus"),
    ("selfHosted", "modelPresetId"): lambda: presets("models"),
    # ponytail: backend only; validate.ts checks profileId is non-empty, because the one profile lives
    # in Python until Step 27 writes shared/profiles/. The UI still shows this 422 on the node.
    ("selfHosted", "profileId"): lambda: PROFILES,
}

_traffic = TypeAdapter(TrafficProfile)


def validate(design: object, config: object = None) -> list[ValidationIssue]:
    """Every problem with a design; empty means it can run. Pass `config` to also check run limits.

    Codes match validate.ts, plus `SCHEMA` for JSON the frontend could never send (a missing edge
    `source`, an unknown node kind): nothing structural can be checked then, so only those are reported.
    """
    issues: list[ValidationIssue] = []

    def add(code: str, message: str, **at: str) -> None:
        issues.append(ValidationIssue(code=code, message=message, **at))

    ranges, schema = _contract_problems(design)
    if schema:
        return schema

    nodes: list[dict] = design["nodes"]  # type: ignore[index]  # the contract parse checked the shape
    edges: list[dict] = design["edges"]  # type: ignore[index]
    by_id = {n["id"]: n for n in nodes}

    if len(nodes) > MAX_NODES:
        add("LIMIT_NODES", f"A design can have at most {MAX_NODES} nodes; this one has {len(nodes)}.")
    if len(edges) > MAX_EDGES:
        add("LIMIT_EDGES", f"A design can have at most {MAX_EDGES} edges; this one has {len(edges)}.")

    # Edges to missing nodes are reported once and then ignored by every other rule.
    for e in edges:
        if e["source"] not in by_id or e["target"] not in by_id:
            add("EDGE_REF", f"Edge {e['id']} points at a node that doesn't exist.", edge_id=e["id"])
    edges = [e for e in edges if e["source"] in by_id and e["target"] in by_id]
    out: dict[str, list[dict]] = {n["id"]: [] for n in nodes}
    incoming = dict.fromkeys(by_id, 0)
    for e in edges:
        out[e["source"]].append(e)
        incoming[e["target"]] += 1

    users = [n for n in nodes if n["kind"] == "users"]
    if not users:
        add("NO_USERS", "Add a Users node: traffic has to start somewhere.")

    for node in nodes:
        o, label, at = out[node["id"]], node["label"], {"node_id": node["id"]}
        match node["kind"]:
            case "users":
                if len(o) != 1 or incoming[node["id"]] > 0:
                    add("USERS_EDGES", f"{label} needs exactly one outgoing edge and no incoming ones.", **at)
            case "loadBalancer":
                if not o:
                    add("LB_NO_TARGETS", f"{label} has nowhere to send traffic. Connect it to a node.", **at)
            case "cache":
                if len(o) != 1:
                    add(
                        "CACHE_EDGES",
                        f"{label} needs exactly one outgoing edge: where cache misses go.",
                        **at,
                    )
            case "database" | "llm":
                if o:
                    add("LEAF_HAS_OUTGOING", f"{label} is a leaf. Remove its outgoing edges.", **at)
            case "agent":
                llm = [e for e in o if e.get("role") == "llm"]
                ok = (
                    len(llm) == 1
                    and by_id[llm[0]["target"]]["kind"] == "llm"
                    and all(e.get("role") in ("llm", "tool") for e in o)
                )
                if not ok:
                    add(
                        "AGENT_EDGES",
                        f'{label} needs exactly one "llm" edge to an LLM node; '
                        'other edges must be "tool" edges.',
                        **at,
                    )

    for e in edges:
        if e.get("role") is not None and by_id[e["source"]]["kind"] != "agent":
            add("ROLE_NOT_ALLOWED", "Only edges leaving an agent can have a role.", edge_id=e["id"])

    if back := _back_edge(nodes, out):
        src, dst = by_id[back["source"]]["label"], by_id[back["target"]]["label"]
        add(
            "CYCLE",
            f"The graph loops back through {src} → {dst}. "
            "Agent loops are modeled inside the agent node; remove this edge.",
            edge_id=back["id"],
        )

    reached = {n["id"] for n in users}
    todo = list(reached)
    while todo:
        for e in out[todo.pop()]:
            if e["target"] not in reached:
                reached.add(e["target"])
                todo.append(e["target"])
    for n in nodes:
        if n["id"] not in reached:
            add(
                "UNREACHABLE",
                f"{n['label']} gets no traffic: no path leads to it from a Users node.",
                node_id=n["id"],
            )

    issues += ranges
    for node in nodes:
        for path, preset_id in _unknown_presets(node):
            add(
                "PARAM_RANGE",
                f'{node["label"]}: unknown preset "{preset_id}".',
                node_id=node["id"],
                path=path,
            )

    # Users nodes whose traffic breaks a field range are already PARAM_RANGE; they add nothing here.
    traffic = [t for t in map(_parsed_traffic, users) if t is not None]
    # ponytail: sums each users node's own peak, so two spikes at different times over-count; exact max
    # if it matters (and change validate.ts to match).
    peak_rps = sum(peak(t) for t in traffic)
    if peak_rps > MAX_RPS:
        add("LIMIT_RATE", f"Traffic peaks at {peak_rps:g} req/s; the limit is {MAX_RPS} req/s.")

    if config is not None:
        issues += _config_problems(config)
        duration_s = config.get("durationS") if isinstance(config, dict) else None
        # Like the frontend, estimate from the given duration even when it is out of range.
        if _is_number(duration_s):
            total = sum(expected_requests(t, duration_s) for t in traffic)
            requests = math.floor(total + 0.5)  # rounds like JS Math.round, not Python's round-half-even
            if requests > MAX_REQUESTS:
                add(
                    "LIMIT_REQUESTS",
                    f"This run would send about {requests} requests; the limit is {MAX_REQUESTS}. "
                    "Shorten it or lower traffic.",
                )
    return issues


# ── Helpers ──────────────────────────────────────────────────────────────────


def _contract_problems(design: object) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    """Parse the design against the contracts → (PARAM_RANGE issues, SCHEMA issues).

    A Pydantic error inside a node's `params` is a field-range problem the user can fix in the
    inspector; anything else means the JSON isn't a design at all.
    """
    try:
        Design.model_validate(design)
        return [], []
    except ValidationError as e:
        errors = e.errors()
    ranges, schema = [], []
    for err in errors:
        loc, message = err["loc"], err["msg"].removeprefix("Value error, ")
        # ("nodes", i, <kind tag>, "params", ...) is a field inside one node's params.
        if len(loc) > 3 and loc[0] == "nodes" and loc[3] == "params":
            node = design["nodes"][loc[1]]  # type: ignore[index]
            path = _json_path(node, loc[3:])
            label = node.get("label", node.get("id"))
            ranges.append(
                ValidationIssue(
                    code="PARAM_RANGE",
                    message=f"{label}: {path.rsplit('.', 1)[-1]}: {message}.",
                    node_id=node.get("id"),
                    path=path,
                )
            )
        else:
            path = ".".join(map(str, loc)) or "design"
            schema.append(ValidationIssue(code="SCHEMA", message=f"{path}: {message}.", path=path))
    return ranges, schema


def _json_path(obj: object, loc: tuple) -> str:
    """Dotted path of a Pydantic error location in the JSON, without the union tags Pydantic inserts.

    Pydantic reports `params.hosted.ttft` for a hosted LLM's `params.ttft`: "hosted" is the value of
    the discriminator (`mode`), not a key, so it is dropped.
    """
    parts = []
    for key in loc:
        tags = (obj.get("kind"), obj.get("type"), obj.get("mode")) if isinstance(obj, dict) else ()
        if key in tags and key not in obj:
            continue
        parts.append(str(key))
        obj = obj.get(key) if isinstance(obj, dict) else None
    return ".".join(parts)


def _config_problems(config: object) -> list[ValidationIssue]:
    try:
        RunConfig.model_validate(config)
        return []
    except ValidationError as e:
        errors = e.errors()
    issues = []
    for err in errors:
        path = ".".join(["config", *map(str, err["loc"])])
        if path == "config.durationS":
            message = f"Run duration must be {MIN_DURATION_S}–{MAX_DURATION_S} s."
            issues.append(ValidationIssue(code="LIMIT_DURATION", message=message, path=path))
        else:
            issues.append(ValidationIssue(code="SCHEMA", message=f"{path}: {err['msg']}.", path=path))
    return issues


def _back_edge(nodes: list[dict], out: dict[str, list[dict]]) -> dict | None:
    """First edge that closes a loop (depth-first, nodes and edges in design order), or None for a DAG.

    Same order as validate.ts's recursive search, but with an explicit stack: an API caller can send
    a chain far deeper than Python's recursion limit before LIMIT_NODES turns it away.
    """
    state: dict[str, str] = {}
    for root in nodes:
        if root["id"] in state:
            continue
        state[root["id"]] = "open"
        stack = [(root["id"], iter(out[root["id"]]))]
        while stack:
            node_id, edges = stack[-1]
            for e in edges:
                if state.get(e["target"]) == "open":
                    return e
                if e["target"] not in state:
                    state[e["target"]] = "open"
                    stack.append((e["target"], iter(out[e["target"]])))
                    break
            else:  # every edge explored
                state[node_id] = "done"
                stack.pop()
    return None


def _unknown_presets(node: dict) -> list[tuple[str, str]]:
    """(path, id) for each preset or profile id on an LLM node that names nothing that exists."""
    params = node.get("params")
    if node["kind"] != "llm" or not isinstance(params, dict):
        return []
    return [
        (f"params.{field}", params[field])
        for (mode, field), known in PRESET_FIELDS.items()
        if params.get("mode") == mode and isinstance(params.get(field), str) and params[field] not in known()
    ]


def _parsed_traffic(users_node: dict) -> TrafficProfile | None:
    try:
        return _traffic.validate_python(users_node["params"]["traffic"])
    except (ValidationError, KeyError, TypeError):
        return None


def _is_number(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)
