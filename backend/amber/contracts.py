"""Pydantic mirror of the data contracts in plan §7 (frontend/src/types/contracts.ts).

Python fields are snake_case; JSON is camelCase, exactly as the frontend writes it. Field ranges come
from the §7.2/§7.3 comments and match PARAM_RANGE in frontend/src/lib/validate.ts. Graph rules (§7.6)
and limits (§3) are not here: they belong to sim/graph.py.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

NodeKind = Literal["users", "loadBalancer", "service", "cache", "database", "agent", "llm"]

# Range shapes that §7.2 reuses across node kinds.
Count = Annotated[int, Field(ge=1)]
NonNegInt = Annotated[int, Field(ge=0)]
NonNeg = Annotated[float, Field(ge=0)]  # rates, seconds, USD
Replicas = Annotated[int, Field(ge=1, le=50)]
QueueLimit = Annotated[int, Field(ge=0, le=10000)]  # waiting requests per replica/pool before 503


class Model(BaseModel):
    """camelCase JSON in and out, unknown keys rejected (catches `p50` vs `p50Ms`), no NaN or infinity."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        extra="forbid",
        allow_inf_nan=False,
    )


# ── 7.2 Node parameters ──────────────────────────────────────────────────────


class LatencyDist(Model):
    """A lognormal latency given by its median and 99th percentile, in milliseconds (§8.3)."""

    p50_ms: float
    p99_ms: float

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not (self.p50_ms > 0 and self.p99_ms >= self.p50_ms):
            raise ValueError("needs p50 > 0 and p99 ≥ p50")
        return self


class ConstantTraffic(Model):
    type: Literal["constant"]
    rps: NonNeg


class SpikeTraffic(Model):
    type: Literal["spike"]
    base_rps: NonNeg
    peak_rps: NonNeg
    peak_start_s: NonNeg
    peak_duration_s: NonNeg


class RampTraffic(Model):
    type: Literal["ramp"]
    start_rps: NonNeg
    end_rps: NonNeg


TrafficProfile = Annotated[ConstantTraffic | SpikeTraffic | RampTraffic, Field(discriminator="type")]


class UsersParams(Model):
    traffic: TrafficProfile
    client_timeout_ms: Annotated[float, Field(ge=1)]


class LoadBalancerParams(Model):
    algorithm: Literal["roundRobin", "leastConnections"]
    overhead: LatencyDist


class ServiceParams(Model):
    replicas: Replicas
    concurrency_per_replica: Annotated[int, Field(ge=1, le=1000)]  # threads/workers
    queue_limit: QueueLimit
    work: LatencyDist  # own processing time, excluding downstream calls
    cost_per_replica_month: NonNeg


class CacheParams(Model):
    hit_rate: Annotated[float, Field(ge=0, le=1)]
    latency: LatencyDist
    cost_per_month: NonNeg


class DatabaseParams(Model):
    preset: Literal["postgres", "mongodb", "vector", "custom"]
    connection_pool: Count
    queue_limit: QueueLimit
    query: LatencyDist
    cost_per_month: NonNeg


class AgentParams(Model):
    llm_calls_mean: Annotated[float, Field(ge=1)]  # calls per request = 1 + Poisson(mean - 1)
    tool_calls_per_step: NonNegInt  # between consecutive LLM calls
    tool_latency: LatencyDist  # used only when the agent has no tool edges
    base_prompt_tokens: Count
    context_growth_tokens_per_step: NonNegInt
    output_tokens_per_call: Count


class TokensPerSecond(Model):
    """Generation speed: the median and the slow 1st percentile (§8.3)."""

    p50: float
    p99_low: float

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not (self.p99_low > 0 and self.p50 >= self.p99_low):
            raise ValueError("needs p99Low > 0 and p50 ≥ p99Low")
        return self


class HostedLlmParams(Model):
    mode: Literal["hosted"]
    preset_id: str  # hosted_llms.json; checked against the presets by sim/graph.py
    ttft: LatencyDist
    tokens_per_second: TokensPerSecond
    input_usd_per_1m: NonNeg
    output_usd_per_1m: NonNeg
    rate_limit_rpm: Annotated[float, Field(ge=1)]
    max_retries: NonNegInt


class Speculative(Model):
    """Speculative decoding. The other fields are only checked when it is enabled."""

    enabled: bool
    draft_tokens: int
    acceptance_rate: float
    draft_step_ms: float

    @model_validator(mode="after")
    def _in_range_when_enabled(self) -> Self:
        if self.enabled and not (
            self.draft_tokens >= 1 and 0 <= self.acceptance_rate <= 1 and self.draft_step_ms >= 0
        ):
            raise ValueError("needs draftTokens ≥ 1, acceptanceRate from 0 to 1, draftStepMs ≥ 0")
        return self


class SelfHostedLlmParams(Model):
    mode: Literal["selfHosted"]
    gpu_preset_id: str  # gpus.json
    model_preset_id: str  # models.json
    profile_id: Annotated[str, Field(min_length=1)]  # shared/profiles; defines prefill/decode timing
    replicas: Replicas
    max_batch_size: Count  # max running sequences
    max_batch_tokens: Count  # prefill token budget per iteration
    max_output_tokens_reserve: Count  # KV reserved per request at admission
    speculative: Speculative


LlmParams = Annotated[HostedLlmParams | SelfHostedLlmParams, Field(discriminator="mode")]


# ── 7.1 Design ───────────────────────────────────────────────────────────────


class Position(Model):
    x: float
    y: float


class NodeBase(Model):
    id: str  # stable, e.g. "n_ab12"
    label: str
    position: Position  # UI only; the simulator ignores it


class UsersNode(NodeBase):
    kind: Literal["users"]
    params: UsersParams


class LoadBalancerNode(NodeBase):
    kind: Literal["loadBalancer"]
    params: LoadBalancerParams


class ServiceNode(NodeBase):
    kind: Literal["service"]
    params: ServiceParams


class CacheNode(NodeBase):
    kind: Literal["cache"]
    params: CacheParams


class DatabaseNode(NodeBase):
    kind: Literal["database"]
    params: DatabaseParams


class AgentNode(NodeBase):
    kind: Literal["agent"]
    params: AgentParams


class LlmNode(NodeBase):
    kind: Literal["llm"]
    params: LlmParams


DesignNode = Annotated[
    UsersNode | LoadBalancerNode | ServiceNode | CacheNode | DatabaseNode | AgentNode | LlmNode,
    Field(discriminator="kind"),
]


class DesignEdge(Model):
    id: str
    source: str
    target: str
    role: Literal["llm", "tool"] | None = None  # only on edges leaving an agent node


class Design(Model):
    id: str | None = None  # assigned by the backend on save
    name: str
    version: Literal[1]
    nodes: list[DesignNode]
    edges: list[DesignEdge]


# ── 7.3 Run configuration ────────────────────────────────────────────────────


class RunConfig(Model):
    duration_s: Annotated[float, Field(ge=10, le=600)]
    seed: int  # same design + config + seed => identical result
    warmup_s: NonNeg = 5  # excluded from summary stats


# ── 7.4 Run result ───────────────────────────────────────────────────────────


class Engine(Model):
    events: int
    wall_ms: float
    events_per_sec: float
    simulated_requests: int


class Percentiles(Model):
    p50: float
    p95: float
    p99: float


class LatencySummary(Percentiles):
    max: float


class Summary(Model):
    requests: int
    completed: int
    errors: int
    timeouts: int
    rejected: int
    throughput_rps: float
    error_rate: float
    latency_ms: LatencySummary
    ttft_ms: Percentiles | None = None


class NodePoint(Model):
    util: float
    queue: float
    rejects: int
    throughput_rps: float


class TimelinePoint(Model):
    t: float  # seconds, bucket start
    arrivals_rps: float
    throughput_rps: float
    error_rate: float
    p50: float
    p95: float
    p99: float
    nodes: dict[str, NodePoint]


class NodeSummary(Model):
    id: str
    kind: NodeKind
    util_avg: float
    util_max: float
    queue_avg: float
    queue_max: float
    rejects: int
    monthly_usd: float


class GpuPoint(Model):
    t: float
    kv_pct: float
    batch: int
    waiting: int


class GpuSeries(Model):
    node_id: str
    points: list[GpuPoint]


class AttributionRow(Model):
    node_id: str
    queue_share: float  # queue and work shares across all rows sum to ~1
    work_share: float


class CostLine(Model):
    node_id: str
    usd: float
    detail: str


class Cost(Model):
    monthly_total_usd: float
    breakdown: list[CostLine]
    assumptions: list[str]


class Bottleneck(Model):
    severity: Literal["info", "warn", "critical"]
    node_id: str | None = None
    message: str


class RunResult(Model):
    run_id: str | None = None
    design_hash: str  # sha256 of canonical design JSON (sorted keys, no positions)
    config: RunConfig
    engine: Engine
    summary: Summary
    timeline: list[TimelinePoint]  # at most 300 points (downsampled buckets)
    nodes: list[NodeSummary]
    gpu: list[GpuSeries]  # one per self-hosted LLM node
    attribution: list[AttributionRow]  # where slow (>= p99) requests spend time
    cost: Cost
    bottlenecks: list[Bottleneck]


# ── 7.5 Validation errors (HTTP 422) ─────────────────────────────────────────


class ValidationIssue(Model):
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    path: str | None = None


class ValidationErrorBody(Model):
    issues: list[ValidationIssue]
