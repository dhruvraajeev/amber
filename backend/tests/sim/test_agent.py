"""The agent node (plan §8.5): how many LLM calls, how big each prompt is, where the tool calls go."""

import statistics
from collections import defaultdict

import pytest
from test_llm_hosted import USD_IN, USD_OUT, llm
from test_nodes import NODE, fixed, send
from test_run import config, template

from amber.contracts import Design
from amber.sim.kernel import Environment, Timeout
from amber.sim.nodes import Node
from amber.sim.nodes.agent import Agent
from amber.sim.nodes.llm_hosted import HostedLlm
from amber.sim.run import execute, simulate

BASE, GROWTH, OUTPUT = 1000, 250, 100


class FakeLlm(Node):
    """Logs every call's sizes and takes `ms` to answer; the call numbered `fail_on` (1-based) fails."""

    def __init__(self, env, log, ms=100.0, fail_on=None):
        super().__init__(env, "llm")
        self.log, self.ms, self.fail_on, self.calls = log, ms, fail_on, 0

    def call(self, req, prompt_tokens, output_tokens):
        self.calls += 1
        self.log.append((req.id, "llm", prompt_tokens, output_tokens))
        yield Timeout(self.env, self.ms)
        if self.calls == self.fail_on:
            req.status = "rate_limited"


class Tool(Node):
    """Logs who called it and takes `ms` to answer; rejects every request if `fails`."""

    def __init__(self, env, log, node_id, ms=10.0, fails=False):
        super().__init__(env, node_id)
        self.log, self.ms, self.fails = log, ms, fails

    def handle(self, req):
        self.log.append((req.id, self.id))
        yield Timeout(self.env, self.ms)
        if self.fails:
            req.status = "rejected"


def agent(env, llm_node, tools=(), mean=3.0, per_step=2, tool_ms=5.0, seed=42):
    params = {
        "llm_calls_mean": mean,
        "tool_calls_per_step": per_step,
        "tool_latency": fixed(tool_ms),
        "base_prompt_tokens": BASE,
        "context_growth_tokens_per_step": GROWTH,
        "output_tokens_per_call": OUTPUT,
    }
    node = NODE.validate_python(
        {"id": "agent", "kind": "agent", "label": "agent", "position": {"x": 0, "y": 0}, "params": params}
    )
    a = Agent(env, node, seed)
    a.connect(llm_node, "llm")
    for tool in tools:
        a.connect(tool, "tool")
    return a


def journeys(log):
    """The log split per request, in call order: request id -> ["llm", "t1", ...]."""
    out = defaultdict(list)
    for entry in log:
        out[entry[0]].append(entry[1])
    return out


def llm_calls(log):
    return {rid: [e for e in trail if e == "llm"] for rid, trail in journeys(log).items()}


# ── How many calls, and how big ──────────────────────────────────────────────


def test_a_mean_of_one_is_always_exactly_one_call_with_the_base_prompt_and_no_tools():
    env, log = Environment(), []
    tools = [Tool(env, log, "t1")]
    reqs = send(env, agent(env, FakeLlm(env, log), tools, mean=1.0), 200)
    assert all(r.status == "ok" for r in reqs)
    assert [e for e in log if e[1] == "t1"] == []
    assert {e[2:] for e in log} == {(BASE, OUTPUT)}
    assert len(log) == 200


def test_call_i_sends_the_base_prompt_plus_i_steps_of_growth_from_the_first_call_to_the_last():
    """The off-by-one §18 warns about: step 0 is the base prompt, step n-1 is base + (n-1) growth."""
    env, log = Environment(), []
    send(env, agent(env, FakeLlm(env, log), mean=4.0), 500, gap_ms=10_000)
    prompts = defaultdict(list)
    for rid, _, prompt, output in log:
        prompts[rid].append(prompt)
        assert output == OUTPUT
    assert max(len(p) for p in prompts.values()) >= 6  # the check has long loops to bite on
    for p in prompts.values():
        assert p == [BASE + i * GROWTH for i in range(len(p))]


def test_the_call_count_averages_llm_calls_mean_and_is_never_zero():
    env, log = Environment(), []
    send(env, agent(env, FakeLlm(env, log, ms=0.0), mean=3.5), 20_000)
    counts = [len(c) for c in llm_calls(log).values()]
    assert len(counts) == 20_000
    assert min(counts) == 1
    assert statistics.fmean(counts) == pytest.approx(3.5, rel=0.02)


def test_adding_a_tool_edge_does_not_change_how_many_calls_each_request_makes():
    """The count has its own "calls" stream, so tool latency draws can't shift it."""

    def counts(with_tool):
        env, log = Environment(), []
        tools = [Tool(env, [], "t1")] if with_tool else []
        send(env, agent(env, FakeLlm(env, log), tools, mean=3.0), 300, gap_ms=10_000)
        return [len(c) for c in llm_calls(log).values()]

    assert counts(with_tool=True) == counts(with_tool=False)


# ── Tool calls ───────────────────────────────────────────────────────────────


def test_tool_calls_come_between_llm_calls_and_never_after_the_last():
    env, log = Environment(), []
    tools = [Tool(env, log, "t")]
    send(env, agent(env, FakeLlm(env, log), tools, mean=4.0, per_step=2), 300, gap_ms=100_000)
    for trail in journeys(log).values():
        n = trail.count("llm")
        assert trail == ["llm"] + ["t", "t", "llm"] * (n - 1)


def test_tool_edges_are_called_round_robin_restarting_with_each_request():
    env, log = Environment(), []
    tools = [Tool(env, log, "a"), Tool(env, log, "b")]
    send(env, agent(env, FakeLlm(env, log), tools, mean=4.0, per_step=3), 200, gap_ms=100_000)
    for trail in journeys(log).values():
        called = [e for e in trail if e != "llm"]
        assert called == ["a", "b"] * (len(called) // 2) + ["a"] * (len(called) % 2)


def test_with_no_tool_edges_each_tool_call_is_a_tool_latency_wait_in_the_agents_own_span():
    env, log = Environment(), []
    reqs = send(env, agent(env, FakeLlm(env, log, ms=100.0), mean=4.0, per_step=2, tool_ms=5.0), 300)
    counts = llm_calls(log)
    for req in reqs:
        n = len(counts[req.id])
        [span] = req.spans  # the fake LLM leaves no spans, so this is the agent's
        assert span.node_id == "agent"
        assert span.work_ms == pytest.approx((n - 1) * 2 * 5.0)
        assert req.end - req.created_at == pytest.approx(n * 100.0 + (n - 1) * 2 * 5.0)


def test_with_tool_edges_the_agents_own_span_is_zero_and_recorded_after_its_calls():
    env = Environment()
    reqs = send(env, agent(env, llm(env), [Tool(env, [], "t")], mean=3.0), 50, gap_ms=100_000)
    for req in reqs:
        assert req.spans[-1] == ("agent", 0.0, 0.0)
        assert {s.node_id for s in req.spans[:-1]} <= {"llm"}  # Tool records no span of its own


# ── Errors ───────────────────────────────────────────────────────────────────


def test_a_failed_llm_call_stops_the_loop():
    env, log = Environment(), []
    [req] = send(env, agent(env, FakeLlm(env, log, fail_on=2), [Tool(env, log, "t")], mean=50.0), 1)
    assert req.status == "rate_limited"
    assert journeys(log)["r0"] == ["llm", "t", "t", "llm"]  # nothing after the failed second call
    assert req.spans[-1].node_id == "agent"  # its span still says how long it spent


def test_a_failed_tool_call_stops_the_loop_before_the_next_llm_call():
    env, log = Environment(), []
    tools = [Tool(env, log, "t", fails=True)]
    [req] = send(env, agent(env, FakeLlm(env, log), tools, mean=50.0, per_step=3), 1)
    assert req.status == "rejected"
    assert journeys(log)["r0"] == ["llm", "t"]


# ── Cost and the real pieces together ────────────────────────────────────────


def test_the_token_bill_is_the_growing_prompts_summed_exactly():
    """With the real hosted LLM: step i bills base + i·growth prompt tokens, so n calls bill
    n·base + growth·n(n−1)/2. Starting the growth at step 1, or stopping one short, breaks this."""
    env = Environment()
    hosted = llm(env, rpm=1e9)
    reqs = send(env, agent(env, hosted, mean=5.0), 400)
    expected = 0.0
    for req in reqs:
        n = sum(s.node_id == "llm" for s in req.spans)
        prompt = n * BASE + GROWTH * n * (n - 1) // 2
        expected += (prompt * USD_IN + n * OUTPUT * USD_OUT) / 1e6
    assert hosted.usd == pytest.approx(expected)


def hosted_agent_design() -> Design:
    """The agent template with its self-hosted LLM swapped for the RAG template's hosted one."""
    raw = template("agent-self-hosted")
    hosted = next(n for n in template("rag-chatbot-hosted")["nodes"] if n["kind"] == "llm")
    next(n for n in raw["nodes"] if n["id"] == "n_llm")["params"] = hosted["params"]
    return Design.model_validate(raw)


def test_a_design_wires_the_agent_by_edge_role():
    run = execute(hosted_agent_design(), config(duration_s=10))
    a = run.nodes["n_agent"]
    assert isinstance(a.llm, HostedLlm) and a.llm is run.nodes["n_llm"]
    assert a.tools == [run.nodes["n_tools"]]
    assert a.downstream == []


def test_an_agent_design_runs_end_to_end_and_repeats_byte_for_byte():
    first = simulate(hosted_agent_design(), config(duration_s=20, seed=3))
    again = simulate(hosted_agent_design(), config(duration_s=20, seed=3))
    drop = {"engine": {"wall_ms", "events_per_sec"}}
    assert first.model_dump(exclude=drop) == again.model_dump(exclude=drop)
    assert first.summary.completed > 0
    assert first.summary.ttft_ms is not None  # the agent's first LLM call sets the user's TTFT
    assert "n_agent" in {n.id for n in first.nodes}
    assert first.cost.monthly_total_usd > 0
