"""The agent node: a loop of LLM calls with tool calls between them, inside one request (plan §8.5)."""

from collections.abc import Generator
from typing import Any

from amber.contracts import AgentNode
from amber.sim.kernel import Environment, Event, ProcessGen, Timeout
from amber.sim.nodes import Node
from amber.sim.nodes.llm_hosted import HostedLlm
from amber.sim.request import Request
from amber.sim.rng import lognormal_from_percentiles, poisson, stream


class Agent(Node):
    """Makes `n = 1 + Poisson(llmCallsMean - 1)` LLM calls per request, so always at least one.

    Call `i` (0-based) sends `basePromptTokens + i * contextGrowthTokensPerStep` prompt tokens: every
    step re-sends the conversation so far, which is what makes agents slow and expensive. Between two
    LLM calls, never after the last one (that call writes the answer), come `toolCallsPerStep` tool
    calls, one after another: to the tool edges round robin, or, with no tool edges, a `toolLatency`
    wait. The round robin restarts with each request, so a request's tool order never depends on
    what other requests are doing.

    The agent's own span is that sampled tool time (zero with tool edges, whose nodes leave their own
    spans). It is recorded when the loop ends, so it follows the spans of the calls it made. No
    capacity limit: the agent's slot is held by whoever called it.
    """

    def __init__(self, env: Environment, node: AgentNode, seed: int) -> None:
        super().__init__(env, node.id)
        p = node.params
        self._calls_mean = p.llm_calls_mean
        self._tool_calls_per_step = p.tool_calls_per_step
        self._tool_latency = lognormal_from_percentiles(p.tool_latency.p50_ms, p.tool_latency.p99_ms)
        self._base_prompt = p.base_prompt_tokens
        self._growth = p.context_growth_tokens_per_step
        self._output = p.output_tokens_per_call
        self._calls_rng = stream(seed, node.id, "calls")
        self._work_rng = stream(seed, node.id, "work")
        # Wired by `sim/run.py` from the edge roles, once every node exists (§7.6 AGENT_EDGES).
        self.llm: HostedLlm | None = None
        self.tools: list[Node] = []

    def connect(self, target: Node, role: str | None) -> None:
        """Attach one outgoing edge: the single `llm` edge, or one more `tool` edge, in edge order."""
        if role == "llm":
            self.llm = target  # an llm node: validation checks where the llm edge points
        else:
            self.tools.append(target)

    def handle(self, req: Request) -> ProcessGen:
        calls = 1 + poisson(self._calls_rng, self._calls_mean - 1)
        tool_ms = yield from self._steps(req, calls)
        self.record(req, 0.0, tool_ms)

    def _steps(self, req: Request, calls: int) -> Generator[Event, Any, float]:
        """Run the loop; return the tool time sampled here. Stops at the first error, like any caller."""
        tool_ms = 0.0
        next_tool = 0
        for step in range(calls):
            if step:  # "between LLM calls" = before every call but the first
                for _ in range(self._tool_calls_per_step):
                    if self.tools:
                        yield from self.tools[next_tool].handle(req)
                        next_tool = (next_tool + 1) % len(self.tools)
                    else:
                        ms = self._work_rng.lognormvariate(*self._tool_latency)
                        yield Timeout(self.env, ms)
                        tool_ms += ms
                    if req.failed:
                        return tool_ms
            yield from self.llm.call(req, self._base_prompt + step * self._growth, self._output)
            if req.failed:
                return tool_ms
        return tool_ms
