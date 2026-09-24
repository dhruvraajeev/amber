"""One design in, one RunResult out (plan §7.4): the entry point everything else in Amber calls.

`simulate` assumes the design already passed `sim/graph.validate` — the API checks that first and
answers 422 on its own. Here a design is turned into node objects, wired up from its edges, run, and
measured. Nothing is random beyond the run's seed, so the same design, config and seed always give
the same result, byte for byte (§8.2). That is what `tests/sim/test_determinism.py` pins down.
"""

import json
import time
from collections.abc import Callable
from hashlib import sha256
from typing import NamedTuple

from amber.contracts import Design, DesignNode, Engine, HostedLlmParams, RunConfig, RunResult
from amber.sim.analysis import attribution, bottlenecks
from amber.sim.cost import monthly_cost
from amber.sim.kernel import Environment
from amber.sim.metrics import Metrics
from amber.sim.nodes import Node
from amber.sim.nodes.cache import Cache
from amber.sim.nodes.database import Database
from amber.sim.nodes.llm_hosted import HostedLlm
from amber.sim.nodes.load_balancer import LoadBalancer
from amber.sim.nodes.service import Service
from amber.sim.nodes.users import Users

# Node kinds that have a class today. `agent` and self-hosted LLMs arrive in Steps 20 and 21.
KINDS = {
    "users": Users,
    "loadBalancer": LoadBalancer,
    "service": Service,
    "cache": Cache,
    "database": Database,
}

# node id -> a function drawing that node's own work time in ms. Test-only (plan §16): the
# queueing-theory tests need exponential work times for the textbook formulas to hold. It is a
# keyword argument, never a contract field, so it cannot reach the HTTP API or the OpenAPI schema.
WorkSamplers = dict[str, Callable[[], float]]


class Run(NamedTuple):
    """A finished run, before it is turned into a `RunResult`."""

    env: Environment
    nodes: dict[str, Node]
    metrics: Metrics
    wall_ms: float


def simulate(
    design: Design,
    config: RunConfig,
    *,
    wall_limit_s: float | None = None,
    work_samplers: WorkSamplers | None = None,
) -> RunResult:
    """Run `design` for `config.durationS` simulated seconds and report what happened.

    With `wall_limit_s`, a run that takes longer than that in real time raises `kernel.SimTimeout`.
    """
    run = execute(design, config, work_samplers, wall_limit_s)
    cost = monthly_cost(design, run.nodes, config.duration_s)
    summary = run.metrics.summary()
    timeline = run.metrics.timeline()
    rows = attribution(run.metrics.answered(), summary.latency_ms.p99)
    nodes = run.metrics.node_summaries(design, {line.node_id: line.usd for line in cost.breakdown})
    gpu = []  # one series per self-hosted LLM node, which Step 21 adds
    return RunResult(
        design_hash=design_hash(design),
        config=config,
        engine=_engine(run),
        summary=summary,
        timeline=timeline,
        nodes=nodes,
        gpu=gpu,
        attribution=rows,
        cost=cost,
        bottlenecks=bottlenecks({n.id: n.label for n in design.nodes}, summary, nodes, timeline, gpu, rows),
    )


def execute(
    design: Design,
    config: RunConfig,
    work_samplers: WorkSamplers | None = None,
    wall_limit_s: float | None = None,
) -> Run:
    """The simulation itself, without the reporting: what `simulate` wraps.

    Tests that need per-request detail (every span, every request) use this; everything else wants
    `simulate`. Order matters: `Metrics` starts its sampler when it is built, so it has to exist
    before the clock moves, and the users nodes start last so nothing arrives before it is watching.
    """
    env = Environment()
    nodes = {node.id: build_node(env, node, config.seed) for node in design.nodes}
    for edge in design.edges:
        nodes[edge.source].downstream.append(nodes[edge.target])
    for node_id, sampler in (work_samplers or {}).items():
        nodes[node_id].sample_work = sampler  # type: ignore[attr-defined]

    metrics = Metrics(env, nodes, config)
    for node in nodes.values():
        if isinstance(node, Users):
            node.start(config.duration_s)

    started_at = time.perf_counter()
    deadline = None if wall_limit_s is None else started_at + wall_limit_s
    env.run(config.duration_s * 1000, deadline)
    return Run(env, nodes, metrics, (time.perf_counter() - started_at) * 1000)


def build_node(env: Environment, node: DesignNode, seed: int) -> Node:
    """The simulated node for one design node."""
    if node.kind == "llm":
        if not isinstance(node.params, HostedLlmParams):
            raise NotImplementedError("self-hosted LLM nodes are not simulated yet")
        return HostedLlm(env, node, seed)
    if node.kind not in KINDS:
        raise NotImplementedError(f"{node.kind} nodes are not simulated yet")
    return KINDS[node.kind](env, node, seed)


def design_hash(design: Design) -> str:
    """SHA-256 of the canonical design JSON (§7.4), the same bytes the frontend hashes."""
    return sha256(canonical_design(design).encode()).hexdigest()


def canonical_design(design: Design) -> str:
    """The design as canonical JSON: sorted keys, no whitespace, no positions, no absent fields.

    It must match `canonicalDesign` in frontend/src/canvas/map.ts byte for byte, so the frontend and
    the backend agree on whether two designs are the same one. Two Python-only wrinkles: fields that
    are `None` here are simply absent in the frontend's object, so they are dropped, and a float that
    happens to be whole is written as an integer, because that is what JavaScript prints.
    """
    body = design.model_dump(mode="json", by_alias=True, exclude_none=True)
    for node in body["nodes"]:
        del node["position"]  # UI only: moving a node must not change the hash
    return json.dumps(_plain(body), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _plain(value: object) -> object:
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _engine(run: Run) -> Engine:
    return Engine(
        events=run.env.events,
        wall_ms=run.wall_ms,
        events_per_sec=run.env.events / run.wall_ms * 1000 if run.wall_ms else 0.0,
        simulated_requests=len(run.metrics.requests),
    )
