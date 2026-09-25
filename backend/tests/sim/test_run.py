"""`simulate()` end to end (plan §7.4): the pieces wired together, and the design hash the UI shares."""

import json

import pytest

from amber.contracts import Design, RunConfig
from amber.presets import SHARED
from amber.sim.analysis import attribution
from amber.sim.nodes.database import Database
from amber.sim.nodes.llm_hosted import HostedLlm
from amber.sim.nodes.llm_selfhosted import SelfHostedLlm
from amber.sim.run import canonical_design, design_hash, execute, simulate

TEMPLATES = SHARED / "templates"


def template(name: str) -> dict:
    return json.loads((TEMPLATES / f"{name}.json").read_text())


def design(name: str) -> Design:
    return Design.model_validate(template(name))


def config(duration_s=30, seed=1, warmup_s=5) -> RunConfig:
    return RunConfig(duration_s=duration_s, seed=seed, warmup_s=warmup_s)


def js_stable_stringify(value) -> str:
    """The frontend's `stableStringify` (canvas/map.ts), written out again here on purpose.

    Checking one implementation against a copy of itself proves nothing, so this is the JavaScript
    rules stated directly: keys sorted, absent fields dropped, arrays in order, no whitespace.
    """
    if isinstance(value, dict):
        keys = sorted(k for k in value if value[k] is not None)
        body = ",".join(f"{json.dumps(k)}:{js_stable_stringify(value[k])}" for k in keys)
        return f"{{{body}}}"
    if isinstance(value, list):
        return f"[{','.join(map(js_stable_stringify, value))}]"
    return json.dumps(value, ensure_ascii=False)


# ── The design hash (§7.4) ───────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["classic-web-app", "rag-chatbot-hosted", "agent-self-hosted"])
def test_canonical_json_is_byte_identical_to_the_frontends(name):
    raw = template(name)
    expected = js_stable_stringify({**raw, "nodes": [{**n, "position": None} for n in raw["nodes"]]})
    assert canonical_design(Design.model_validate(raw)) == expected


def test_moving_a_node_keeps_the_hash_but_renaming_the_design_changes_it():
    raw = template("classic-web-app")
    moved = {**raw, "nodes": [{**n, "position": {"x": 99, "y": 99}} for n in raw["nodes"]]}
    renamed = {**raw, "name": "Classic web app (copy)"}

    assert design_hash(Design.model_validate(moved)) == design_hash(Design.model_validate(raw))
    assert design_hash(Design.model_validate(renamed)) != design_hash(Design.model_validate(raw))
    assert len(design_hash(Design.model_validate(raw))) == 64


def test_whole_floats_are_written_the_way_javascript_writes_them():
    """`clientTimeoutMs` is a float in Python and a number in JS: 5000, never 5000.0."""
    assert '"clientTimeoutMs":5000,' in canonical_design(design("classic-web-app"))


# ── Building and wiring the graph ────────────────────────────────────────────


def test_edges_become_downstream_links_in_edge_order():
    """A service calls its targets in edge order (§8.5), so the order of `edges` has to survive."""
    run = execute(design("rag-chatbot-hosted"), config())
    kinds = [type(node) for node in run.nodes["n_api"].downstream]
    assert kinds == [Database, HostedLlm]  # n_api → n_vec, then n_api → n_llm
    assert run.nodes["n_users"].downstream == [run.nodes["n_api"]]
    assert run.nodes["n_vec"].downstream == []


def test_an_llm_nodes_mode_picks_its_class():
    """Same `kind`, a different params union member: the mode has to be checked, not just the kind."""
    raw = template("rag-chatbot-hosted")
    llm = next(n for n in raw["nodes"] if n["id"] == "n_llm")
    llm["params"] = next(n for n in template("agent-self-hosted")["nodes"] if n["id"] == "n_llm")["params"]

    assert isinstance(execute(design("rag-chatbot-hosted"), config()).nodes["n_llm"], HostedLlm)
    assert isinstance(execute(Design.model_validate(raw), config()).nodes["n_llm"], SelfHostedLlm)
    assert execute(design("agent-self-hosted"), config()).nodes["n_agent"].llm.__class__ is SelfHostedLlm


def test_the_self_hosted_template_runs_end_to_end():
    result = simulate(design("agent-self-hosted"), config(duration_s=60))

    [series] = result.gpu
    assert series.node_id == "n_llm"
    assert [p.t for p in series.points] == list(range(1, 61))  # a snapshot at the end of every second
    assert all(0 <= p.kv_pct <= 1 and 0 <= p.batch <= 32 for p in series.points)  # maxBatchSize 32
    assert max(p.batch for p in series.points) > 0
    assert result.summary.completed > 0 and result.summary.ttft_ms is not None
    assert result.summary.ttft_ms.p50 < result.summary.latency_ms.p50  # first token well before the end
    llm = next(n for n in result.nodes if n.id == "n_llm")
    assert 0 < llm.util_avg <= 1  # the batch as its slots: a GPU at work no longer reads 0%
    assert result.cost.monthly_total_usd == pytest.approx(2 * 30 + 0.8 * 730 + 15 + 70)  # API, L4, tools, DB


def test_every_reserved_byte_of_kv_is_freed_once_the_traffic_drains():
    run = execute(design("agent-self-hosted"), config(duration_s=30))
    run.env.run(10_000_000)  # arrivals stopped at 30 s; let every request in flight finish
    llm = run.nodes["n_llm"]

    assert [(r.kv_used, r.load) for r in llm.replicas] == [(0, 0)]  # exactly 0: ints, no float drift
    assert all(r.end is not None for r in run.metrics.requests)


# ── The result (§7.4) ────────────────────────────────────────────────────────


def test_a_run_reports_traffic_nodes_cost_and_findings():
    result = simulate(design("classic-web-app"), config(duration_s=30))

    assert result.design_hash == design_hash(design("classic-web-app"))
    assert result.config == config(duration_s=30)
    assert result.summary.requests == pytest.approx(200 * 25, rel=0.05)  # 200 rps, warmup excluded
    s = result.summary
    assert s.errors == s.timeouts == 0  # nothing is overloaded here
    assert 0 <= s.requests - s.completed < 10  # only the last few ms of arrivals are still running
    assert [n.id for n in result.nodes] == [n["id"] for n in template("classic-web-app")["nodes"]]
    assert len(result.timeline) == 30  # one point per second, well under the 300-point cap
    assert result.cost.monthly_total_usd == 4 * 30 + 25 + 60  # 4 API replicas, cache, database
    assert {n.id: n.monthly_usd for n in result.nodes}["n_api"] == 120
    assert sum(r.queue_share + r.work_share for r in result.attribution) == pytest.approx(1)
    assert result.attribution == attribution(  # the slowest 1%, not some other cut of the traffic
        execute(design("classic-web-app"), config(duration_s=30)).metrics.answered(),
        result.summary.latency_ms.p99,
    )
    assert result.bottlenecks  # always at least the "nothing to report" line
    assert result.gpu == []  # no self-hosted LLM in this design


def test_the_engine_block_counts_what_actually_happened():
    run = execute(design("classic-web-app"), config(duration_s=30))
    result = simulate(design("classic-web-app"), config(duration_s=30))

    assert result.engine.events == run.env.events > 10_000
    assert result.engine.simulated_requests == len(run.metrics.requests)
    assert result.engine.simulated_requests > result.summary.requests  # warmup arrivals count here
    assert result.engine.wall_ms > 0
    assert result.engine.events_per_sec == pytest.approx(result.engine.events / result.engine.wall_ms * 1000)


def test_an_overloaded_design_rejects_requests_and_says_which_node():
    """Two slots for 200 rps of 15 ms work: the queue fills, the service turns requests away."""
    raw = template("classic-web-app")
    api = next(n for n in raw["nodes"] if n["id"] == "n_api")
    api["params"] |= {"replicas": 1, "concurrencyPerReplica": 2, "queueLimit": 10}
    result = simulate(Design.model_validate(raw), config(duration_s=20))

    assert result.summary.rejected > 0
    assert result.summary.error_rate > 0.5
    assert {n.id: n.rejects for n in result.nodes}["n_api"] == result.summary.rejected
    critical = [b for b in result.bottlenecks if b.severity == "critical" and b.node_id == "n_api"]
    assert critical
    assert all("API" in b.message for b in critical)  # the node's label, not its id


def test_an_overloaded_run_counts_requests_stuck_past_their_deadline_as_timeouts():
    """Two slots for 200 rps and a 2 s client timeout, with room to queue everyone: the line grows all
    run, so most requests are still waiting when it ends. Those whose user gave up are timeouts."""
    raw = template("classic-web-app")
    nodes = {n["id"]: n for n in raw["nodes"]}
    nodes["n_users"]["params"]["clientTimeoutMs"] = 2000
    nodes["n_api"]["params"] |= {"replicas": 1, "concurrencyPerReplica": 2, "queueLimit": 10_000}
    run = execute(Design.model_validate(raw), config(duration_s=20))
    s = run.metrics.summary()

    waiting = [req for req, out in run.metrics.measured_outcomes if out is None]
    cut_off = [req for req, out in run.metrics.measured_outcomes if out and out.latency_ms is None]
    assert s.requests - s.completed - s.errors - s.timeouts == len(waiting)
    assert all(req.deadline >= 20_000 for req in waiting)  # only users still inside their timeout
    assert len(waiting) < 2 * 200 * 1.5  # at most ~2 s of arrivals, not the whole backlog
    assert cut_off and all(req.end is None and req.deadline < 20_000 for req in cut_off)
    assert s.timeouts > len(cut_off) > s.completed  # most of the backlog, already given up on
    assert s.error_rate > 0.9


def test_the_work_sampler_override_replaces_a_services_own_work_time():
    """The test-only seam the queueing-theory proofs need (§16). It is not part of any contract."""
    run = execute(design("classic-web-app"), config(duration_s=20), {"n_api": lambda: 40.0})
    work = [s.work_ms for r in run.metrics.requests for s in r.spans if s.node_id == "n_api"]

    assert work and set(work) == {40.0}
    assert "work_samplers" not in RunConfig.model_fields
