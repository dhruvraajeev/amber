// Data contracts shared by frontend, backend, MongoDB and MCP (plan §7).
// Field names are law: mirror them exactly in backend/amber/contracts.py (phase 1).
// From phase 2 this file is replaced by types generated from the backend's OpenAPI schema.

// ── 7.1 Design ──────────────────────────────────────────────────────────────

export type NodeKind = 'users' | 'loadBalancer' | 'service' | 'cache' | 'database' | 'agent' | 'llm'

export interface Design {
  id?: string // assigned by backend on save
  name: string
  version: 1
  nodes: DesignNode[]
  edges: DesignEdge[]
}

// Discriminated by `kind`, so `params` narrows to the matching NodeParams (7.2).
export type DesignNode = {
  [K in NodeKind]: {
    id: string // stable, e.g. "n_ab12"
    kind: K
    label: string
    position: { x: number; y: number } // UI only; simulator ignores
    params: NodeParamsByKind[K]
  }
}[NodeKind]

export interface DesignEdge {
  id: string
  source: string
  target: string
  role?: 'llm' | 'tool' // ONLY on edges leaving an agent node
}

// ── 7.2 Node parameters ─────────────────────────────────────────────────────
// Distributions use p50/p99 in milliseconds everywhere (lognormal, §8.3).

export interface LatencyDist {
  p50Ms: number
  p99Ms: number
}

export type TrafficProfile =
  | { type: 'constant'; rps: number }
  | { type: 'spike'; baseRps: number; peakRps: number; peakStartS: number; peakDurationS: number }
  | { type: 'ramp'; startRps: number; endRps: number }

export interface UsersParams {
  traffic: TrafficProfile
  clientTimeoutMs: number
}

export interface LoadBalancerParams {
  algorithm: 'roundRobin' | 'leastConnections'
  overhead: LatencyDist
}

export interface ServiceParams {
  replicas: number // 1..50
  concurrencyPerReplica: number // 1..1000 (threads/workers)
  queueLimit: number // waiting requests per replica before 503 (0..10000)
  work: LatencyDist // own processing time, excluding downstream calls
  costPerReplicaMonth: number // USD
}

export interface CacheParams {
  hitRate: number // 0..1
  latency: LatencyDist
  costPerMonth: number
}

export interface DatabaseParams {
  preset: 'postgres' | 'mongodb' | 'vector' | 'custom'
  connectionPool: number
  queueLimit: number
  query: LatencyDist
  costPerMonth: number
}

export interface AgentParams {
  llmCallsMean: number // mean LLM calls per request (>=1), Poisson(mean-1)+1
  toolCallsPerStep: number // tool calls between consecutive LLM calls
  toolLatency: LatencyDist // used only when the agent has no tool edges
  basePromptTokens: number
  contextGrowthTokensPerStep: number
  outputTokensPerCall: number
}

export interface HostedLlmParams {
  mode: 'hosted'
  presetId: string // hosted_llms.json
  ttft: LatencyDist
  tokensPerSecond: { p50: number; p99Low: number }
  inputUsdPer1M: number
  outputUsdPer1M: number
  rateLimitRpm: number
  maxRetries: number
}

export interface SelfHostedLlmParams {
  mode: 'selfHosted'
  gpuPresetId: string // gpus.json
  modelPresetId: string // models.json
  profileId: string // shared/profiles; defines prefill/decode timing
  replicas: number
  maxBatchSize: number // max running sequences
  maxBatchTokens: number // prefill token budget per iteration
  maxOutputTokensReserve: number // KV reserved per request at admission
  speculative: { enabled: boolean; draftTokens: number; acceptanceRate: number; draftStepMs: number }
}

export type LlmParams = HostedLlmParams | SelfHostedLlmParams

export interface NodeParamsByKind {
  users: UsersParams
  loadBalancer: LoadBalancerParams
  service: ServiceParams
  cache: CacheParams
  database: DatabaseParams
  agent: AgentParams
  llm: LlmParams
}

export type NodeParams = NodeParamsByKind[NodeKind]

// ── 7.3 Run configuration ───────────────────────────────────────────────────

export interface RunConfig {
  durationS: number // 10..600
  seed: number // integer; same design+config+seed => identical result
  warmupS: number // excluded from summary stats (default 5)
}

// ── 7.4 Run result ──────────────────────────────────────────────────────────

export interface RunResult {
  runId?: string
  designHash: string // sha256 of canonical design JSON (sorted keys, no positions)
  config: RunConfig
  engine: { events: number; wallMs: number; eventsPerSec: number; simulatedRequests: number }
  summary: {
    requests: number
    completed: number
    errors: number
    timeouts: number
    rejected: number
    throughputRps: number
    errorRate: number
    latencyMs: { p50: number; p95: number; p99: number; max: number }
    ttftMs?: { p50: number; p95: number; p99: number }
  }
  timeline: TimelinePoint[] // <= 300 points (downsampled buckets)
  nodes: NodeSummary[]
  gpu: GpuSeries[] // one per self-hosted LLM node
  attribution: AttributionRow[] // where slow (>= p99) requests spend time
  cost: {
    monthlyTotalUsd: number
    breakdown: { nodeId: string; usd: number; detail: string }[]
    assumptions: string[]
  }
  bottlenecks: { severity: 'info' | 'warn' | 'critical'; nodeId?: string; message: string }[]
}

export interface TimelinePoint {
  t: number // seconds (bucket start)
  arrivalsRps: number
  throughputRps: number
  errorRate: number
  p50: number
  p95: number
  p99: number
  nodes: Record<string, { util: number; queue: number; rejects: number; throughputRps: number }>
}

export interface NodeSummary {
  id: string
  kind: NodeKind
  utilAvg: number
  utilMax: number
  queueAvg: number
  queueMax: number
  rejects: number
  monthlyUsd: number
}

export interface GpuSeries {
  nodeId: string
  points: { t: number; kvPct: number; batch: number; waiting: number }[]
}

export interface AttributionRow {
  nodeId: string
  queueShare: number
  workShare: number
} // shares sum ~1

// ── 7.5 Validation errors (HTTP 422) ────────────────────────────────────────

export interface ValidationIssue {
  code: string
  message: string
  nodeId?: string
  edgeId?: string
  path?: string
}

export interface ValidationErrorBody {
  issues: ValidationIssue[]
}

// ── Presets (shared/presets/*.json, Appendix A) ─────────────────────────────
// Every price is unverified until someone checks it: verifiedAt stays null until then.

interface PresetBase {
  id: string
  name: string
  verifiedAt: string | null // ISO date the prices were last checked
  note?: string
}

export interface GpuPreset extends PresetBase {
  memoryGb: number
  usdPerHour: number
}

export interface ModelPreset extends PresetBase {
  nLayers: number
  nKvHeads: number
  headDim: number
  bytesPerElement: number // of the KV cache
  weightsGb: number
  defaultPromptTokens: number
  defaultOutputTokens: number
}

export interface HostedLlmPreset
  extends PresetBase,
    Pick<HostedLlmParams, 'ttft' | 'tokensPerSecond' | 'inputUsdPer1M' | 'outputUsdPer1M' | 'rateLimitRpm'> {
  defaultPromptTokens: number
  defaultOutputTokens: number
}

export interface DatabasePreset extends PresetBase, DatabaseParams {}

export interface ServicePreset extends PresetBase, Omit<ServiceParams, 'replicas'> {}
