"""The hosted LLM node: a provider's API behind a rate limit, billed per LLM token (plan §8.6)."""

from amber.contracts import HostedLlmParams, LlmNode
from amber.presets import presets
from amber.sim.kernel import Environment, ProcessGen, Timeout
from amber.sim.nodes import Node
from amber.sim.request import Request
from amber.sim.rng import lognormal_from_p50_p1, lognormal_from_percentiles, stream

BACKOFF_BASE_MS = 500
BACKOFF_CAP_MS = 8000
JITTER_MS = 500  # extra wait drawn uniformly from [0, JITTER_MS), so throttled clients spread out


class HostedLlm(Node):
    """A call waits for the first LLM token (`ttft`), then streams the output at `tokensPerSecond`.

    The provider absorbs any load, so there is no queue and no concurrency cap: the only limit is
    `rateLimitRpm`. That is a bucket of rate-limit *permits* (never called tokens here, to keep them
    apart from LLM tokens): it holds up to `rateLimitRpm`, starts full and refills continuously.
    A call that finds it empty gets a 429, backs off and retries up to `maxRetries` times, then the
    request fails as `rate_limited`. The span's `queue_ms` is that backoff time; `work_ms` is the call.

    `usd` is what completed calls cost. `rejects` counts 429s, retried or not: for this node a reject is
    a rate-limit hit, and Step 15's rate-limit rule reads it that way.
    """

    def __init__(self, env: Environment, node: LlmNode, seed: int) -> None:
        super().__init__(env, node.id)
        p: HostedLlmParams = node.params  # Step 16 builds this class only for mode "hosted"
        preset = presets("hosted_llms")[p.preset_id]
        self.default_tokens = (preset["defaultPromptTokens"], preset["defaultOutputTokens"])
        self._ttft = lognormal_from_percentiles(p.ttft.p50_ms, p.ttft.p99_ms)
        self._tps = lognormal_from_p50_p1(p.tokens_per_second.p50, p.tokens_per_second.p99_low)
        self._usd_per_token = (p.input_usd_per_1m / 1e6, p.output_usd_per_1m / 1e6)
        self._max_retries = p.max_retries

        self._capacity = p.rate_limit_rpm
        self._refill_per_ms = p.rate_limit_rpm / 60_000
        self._permits = p.rate_limit_rpm
        self._refilled_at = 0.0

        self._work_rng = stream(seed, node.id, "work")
        self._tokens_rng = stream(seed, node.id, "tokens")
        self._retry_rng = stream(seed, node.id, "retry")
        self.usd = 0.0

    def handle(self, req: Request) -> ProcessGen:
        """Called straight from a service: the preset's default prompt and output sizes (§8.5)."""
        return self.call(req, *self.default_tokens)

    def call(self, req: Request, prompt_tokens: int, output_tokens: int) -> ProcessGen:
        """One LLM call of the given size. The agent node (Step 20) calls this with growing prompts."""
        started_at = self.env.now
        attempt = 0
        while not self._take_permit():
            self.rejects += 1
            if attempt == self._max_retries:
                req.status = "rate_limited"
                return
            yield Timeout(self.env, self.backoff_ms(attempt))
            attempt += 1
        backoff_ms = self.env.now - started_at

        ttft_ms = self._work_rng.lognormvariate(*self._ttft)
        yield Timeout(self.env, ttft_ms)
        if req.first_token_at is None:  # what the user sees is the first call's first token
            req.first_token_at = self.env.now
        generate_ms = output_tokens / self._tokens_rng.lognormvariate(*self._tps) * 1000
        yield Timeout(self.env, generate_ms)

        self.record(req, backoff_ms, ttft_ms + generate_ms)
        usd_in, usd_out = self._usd_per_token
        self.usd += prompt_tokens * usd_in + output_tokens * usd_out

    def backoff_ms(self, attempt: int) -> float:
        """Wait before retry number `attempt` (0-based): exponential, capped, plus jitter."""
        return min(BACKOFF_CAP_MS, BACKOFF_BASE_MS * 2**attempt) + self._retry_rng.uniform(0, JITTER_MS)

    def _take_permit(self) -> bool:
        """Top the bucket up for the time since the last look, then spend one permit if there is one."""
        now = self.env.now
        self._permits = min(self._capacity, self._permits + (now - self._refilled_at) * self._refill_per_ms)
        self._refilled_at = now
        if self._permits < 1:
            return False
        self._permits -= 1
        return True
