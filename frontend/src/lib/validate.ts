// Graph rules (plan §7.6) and limits (§3). The backend mirrors this in sim/graph.py (Step 12),
// and both are tested against the same fixtures in shared/fixtures/graph/, so keep them in step.

import gpus from '@shared/presets/gpus.json'
import hostedLlms from '@shared/presets/hosted_llms.json'
import models from '@shared/presets/models.json'
import type { Design, DesignEdge, DesignNode, LatencyDist, RunConfig, TrafficProfile, ValidationIssue } from '../api/api'
import { kvBudget } from './ai'
import { estimateDesignRequests } from './estimate'

export const LIMITS = { nodes: 50, edges: 100, minDurationS: 10, maxDurationS: 600, rps: 5000, requests: 200_000 }

export const RULE_CODES = [
  'NO_USERS', 'CYCLE', 'USERS_EDGES', 'LB_NO_TARGETS', 'CACHE_EDGES', 'LEAF_HAS_OUTGOING', 'AGENT_EDGES',
  'ROLE_NOT_ALLOWED', 'UNREACHABLE', 'PARAM_RANGE', 'EDGE_REF',
  'LIMIT_NODES', 'LIMIT_EDGES', 'LIMIT_DURATION', 'LIMIT_RATE', 'LIMIT_REQUESTS',
] as const

/** Every problem with a design; empty means it can run. Pass `config` to also check run limits. */
export function validate(design: Design, config?: RunConfig): ValidationIssue[] {
  const issues: ValidationIssue[] = []
  const add = (code: (typeof RULE_CODES)[number], message: string, at: Partial<ValidationIssue> = {}) =>
    issues.push({ code, message, ...at })
  const byId = new Map(design.nodes.map((n) => [n.id, n]))

  if (design.nodes.length > LIMITS.nodes)
    add('LIMIT_NODES', `A design can have at most ${LIMITS.nodes} nodes; this one has ${design.nodes.length}.`)
  if (design.edges.length > LIMITS.edges)
    add('LIMIT_EDGES', `A design can have at most ${LIMITS.edges} edges; this one has ${design.edges.length}.`)

  // Edges to missing nodes are reported once and then ignored by every other rule.
  const edges = design.edges.filter((e) => {
    const ok = byId.has(e.source) && byId.has(e.target)
    if (!ok) add('EDGE_REF', `Edge ${e.id} points at a node that doesn't exist.`, { edgeId: e.id })
    return ok
  })
  const out = new Map<string, DesignEdge[]>(design.nodes.map((n) => [n.id, []]))
  const into = new Map<string, DesignEdge[]>(design.nodes.map((n) => [n.id, []]))
  for (const e of edges) {
    out.get(e.source)!.push(e)
    into.get(e.target)!.push(e)
  }

  const users = design.nodes.filter((n) => n.kind === 'users')
  if (users.length === 0) add('NO_USERS', 'Add a Users node: traffic has to start somewhere.')

  for (const node of design.nodes) {
    const o = out.get(node.id)!
    const at = { nodeId: node.id }
    switch (node.kind) {
      case 'users':
        if (o.length !== 1 || into.get(node.id)!.length > 0)
          add('USERS_EDGES', `${node.label} needs exactly one outgoing edge and no incoming ones.`, at)
        break
      case 'loadBalancer':
        if (o.length === 0) add('LB_NO_TARGETS', `${node.label} has nowhere to send traffic. Connect it to a node.`, at)
        break
      case 'cache':
        if (o.length !== 1) add('CACHE_EDGES', `${node.label} needs exactly one outgoing edge: where cache misses go.`, at)
        break
      case 'database':
      case 'llm':
        if (o.length > 0) add('LEAF_HAS_OUTGOING', `${node.label} is a leaf. Remove its outgoing edges.`, at)
        break
      case 'agent': {
        const llm = o.filter((e) => e.role === 'llm')
        const ok =
          llm.length === 1 && byId.get(llm[0].target)!.kind === 'llm' && o.every((e) => e.role === 'llm' || e.role === 'tool')
        if (!ok) add('AGENT_EDGES', `${node.label} needs exactly one "llm" edge to an LLM node; other edges must be "tool" edges.`, at)
        break
      }
    }
  }

  for (const e of edges)
    if (e.role !== undefined && byId.get(e.source)!.kind !== 'agent')
      add('ROLE_NOT_ALLOWED', 'Only edges leaving an agent can have a role.', { edgeId: e.id })

  const back = findBackEdge(design.nodes, out)
  if (back)
    add(
      'CYCLE',
      `The graph loops back through ${byId.get(back.source)!.label} → ${byId.get(back.target)!.label}. ` +
        'Agent loops are modeled inside the agent node; remove this edge.',
      { edgeId: back.id },
    )

  const reached = new Set(users.map((n) => n.id))
  const todo = [...reached]
  for (let id = todo.pop(); id !== undefined; id = todo.pop())
    for (const e of out.get(id)!) {
      if (reached.has(e.target)) continue
      reached.add(e.target)
      todo.push(e.target)
    }
  for (const n of design.nodes)
    if (!reached.has(n.id)) add('UNREACHABLE', `${n.label} gets no traffic: no path leads to it from a Users node.`, { nodeId: n.id })

  for (const node of design.nodes) {
    const callers = into.get(node.id)!.map((edge): Caller => ({ edge, source: byId.get(edge.source)! }))
    for (const [path, what] of paramProblems(node, callers))
      add('PARAM_RANGE', `${node.label}: ${what}`, { nodeId: node.id, path: `params.${path}` })
  }

  // ponytail: sums each users node's own peak, so two spikes at different times over-count; exact max if it matters.
  const peakRps = users.reduce((sum, n) => sum + (n.kind === 'users' ? peak(n.params.traffic) : 0), 0)
  if (peakRps > LIMITS.rps) add('LIMIT_RATE', `Traffic peaks at ${peakRps} req/s; the limit is ${LIMITS.rps} req/s.`)

  if (config) {
    if (!(config.durationS >= LIMITS.minDurationS && config.durationS <= LIMITS.maxDurationS))
      add('LIMIT_DURATION', `Run duration must be ${LIMITS.minDurationS}–${LIMITS.maxDurationS} s.`, { path: 'config.durationS' })
    const requests = Math.round(estimateDesignRequests(design, config.durationS))
    if (requests > LIMITS.requests)
      add('LIMIT_REQUESTS', `This run would send about ${requests} requests; the limit is ${LIMITS.requests}. Shorten it or lower traffic.`)
  }
  return issues
}

/** First edge that closes a loop (depth-first, nodes and edges in design order), or null for a DAG. */
function findBackEdge(nodes: DesignNode[], out: Map<string, DesignEdge[]>): DesignEdge | null {
  const state = new Map<string, 'open' | 'done'>()
  const visit = (id: string): DesignEdge | null => {
    state.set(id, 'open')
    for (const e of out.get(id)!) {
      if (state.get(e.target) === 'open') return e
      if (!state.has(e.target)) {
        const found = visit(e.target)
        if (found) return found
      }
    }
    state.set(id, 'done')
    return null
  }
  for (const n of nodes) {
    if (state.has(n.id)) continue
    const found = visit(n.id)
    if (found) return found
  }
  return null
}

function peak(t: TrafficProfile): number {
  if (t.type === 'constant') return t.rps
  if (t.type === 'spike') return Math.max(t.baseRps, t.peakRps)
  return Math.max(t.startRps, t.endRps)
}

// ── Parameter ranges (§7.2 comments). Each problem is [path under params, message]. ──
// Written as `!(ok)` so NaN (an emptied number field) always fails.

type Problem = [path: string, message: string]
/** One incoming edge and the node it comes from. */
type Caller = { edge: DesignEdge; source: DesignNode }

const within = (path: string, v: number, lo: number, hi = Infinity, whole = false): Problem[] =>
  v >= lo && v <= hi && (!whole || Number.isInteger(v))
    ? []
    : [[path, `${path.split('.').pop()} must be ${whole ? 'a whole number ' : ''}${hi === Infinity ? `≥ ${lo}` : `from ${lo} to ${hi}`}.`]]

const dist = (path: string, d: LatencyDist): Problem[] =>
  d.p50Ms > 0 && d.p99Ms >= d.p50Ms ? [] : [[path, `${path.split('.').pop()} needs p50 > 0 and p99 ≥ p50.`]]

const known = (path: string, id: string, list: { id: string }[]): Problem[] =>
  list.some((p) => p.id === id) ? [] : [[path, `unknown preset "${id}".`]]

// A self-hosted model needs its weights to leave room for the KV cache (§8.7; backend: kv_capacity_bytes).
function modelFits(gpuId: string, modelId: string): Problem[] {
  const kv = kvBudget(gpuId, modelId)
  if (!kv) return [] // an unknown id is its own issue
  return kv.capacityBytes > 0 ? [] : [['gpuPresetId',
    `the model does not fit on this GPU (${kv.weightsGb} GB of weights, ${Number(kv.usableGb.toFixed(2))} GB usable on the ${kv.gpuName}).`]]
}

// Admission sets aside KV for the prompt plus the output reserve (§8.7) and nothing grows it later, so the
// reserve must cover the longest answer a caller asks for: an agent's llm edge asks for its
// outputTokensPerCall, any other caller for the model's defaultOutputTokens (§8.5). The largest ask is
// reported; ties go to the first edge. Backend: graph._reserve_too_small, same words.
function reserveCoversOutput(reserve: number, modelId: string, callers: Caller[]): Problem[] {
  const model = models.find((m) => m.id === modelId)
  if (!model || !isCount(reserve)) return [] // an unknown id or a bad reserve is its own issue
  let need = 0
  let who = ''
  for (const { edge, source } of callers) {
    const [tokens, asker] =
      source.kind === 'agent' && edge.role === 'llm'
        ? [source.params.outputTokensPerCall, `${source.label} asks for per call`]
        : [model.defaultOutputTokens, `the model writes by default for calls from ${source.label}`]
    if (isCount(tokens) && tokens > need) [need, who] = [tokens, asker]
  }
  return need <= reserve ? [] : [['maxOutputTokensReserve',
    `the output reserve (${reserve} tokens) is smaller than the ${need} tokens ${who}. Raise maxOutputTokensReserve to at least ${need}.`]]
}

const isCount = (v: number) => Number.isInteger(v) && v >= 1

function paramProblems(node: DesignNode, callers: Caller[]): Problem[] {
  switch (node.kind) {
    case 'users': {
      const { traffic: t, clientTimeoutMs } = node.params
      const rates =
        t.type === 'constant' ? [within('traffic.rps', t.rps, 0)]
        : t.type === 'spike'
          ? [within('traffic.baseRps', t.baseRps, 0), within('traffic.peakRps', t.peakRps, 0),
             within('traffic.peakStartS', t.peakStartS, 0), within('traffic.peakDurationS', t.peakDurationS, 0)]
          : [within('traffic.startRps', t.startRps, 0), within('traffic.endRps', t.endRps, 0)]
      return [...rates.flat(), ...within('clientTimeoutMs', clientTimeoutMs, 1)]
    }
    case 'loadBalancer':
      return dist('overhead', node.params.overhead)
    case 'service': {
      const p = node.params
      return [
        ...within('replicas', p.replicas, 1, 50, true),
        ...within('concurrencyPerReplica', p.concurrencyPerReplica, 1, 1000, true),
        ...within('queueLimit', p.queueLimit, 0, 10000, true),
        ...dist('work', p.work),
        ...within('costPerReplicaMonth', p.costPerReplicaMonth, 0),
      ]
    }
    case 'cache': {
      const p = node.params
      return [...within('hitRate', p.hitRate, 0, 1), ...dist('latency', p.latency), ...within('costPerMonth', p.costPerMonth, 0)]
    }
    case 'database': {
      const p = node.params
      return [
        ...within('connectionPool', p.connectionPool, 1, Infinity, true),
        ...within('queueLimit', p.queueLimit, 0, 10000, true),
        ...dist('query', p.query),
        ...within('costPerMonth', p.costPerMonth, 0),
      ]
    }
    case 'agent': {
      const p = node.params
      return [
        ...within('llmCallsMean', p.llmCallsMean, 1),
        ...within('toolCallsPerStep', p.toolCallsPerStep, 0, Infinity, true),
        ...dist('toolLatency', p.toolLatency),
        ...within('basePromptTokens', p.basePromptTokens, 1, Infinity, true),
        ...within('contextGrowthTokensPerStep', p.contextGrowthTokensPerStep, 0, Infinity, true),
        ...within('outputTokensPerCall', p.outputTokensPerCall, 1, Infinity, true),
      ]
    }
    case 'llm': {
      const p = node.params
      if (p.mode === 'hosted') {
        const tps = p.tokensPerSecond
        return [
          ...known('presetId', p.presetId, hostedLlms),
          ...dist('ttft', p.ttft),
          ...(tps.p99Low > 0 && tps.p50 >= tps.p99Low ? [] : [['tokensPerSecond', 'tokensPerSecond needs p99Low > 0 and p50 ≥ p99Low.'] as Problem]),
          ...within('inputUsdPer1M', p.inputUsdPer1M, 0),
          ...within('outputUsdPer1M', p.outputUsdPer1M, 0),
          ...within('rateLimitRpm', p.rateLimitRpm, 1),
          ...within('maxRetries', p.maxRetries, 0, Infinity, true),
        ]
      }
      const s = p.speculative
      return [
        ...known('gpuPresetId', p.gpuPresetId, gpus),
        ...known('modelPresetId', p.modelPresetId, models),
        ...modelFits(p.gpuPresetId, p.modelPresetId),
        ...reserveCoversOutput(p.maxOutputTokensReserve, p.modelPresetId, callers),
        ...(p.profileId ? [] : [['profileId', 'profileId is required.'] as Problem]),
        ...within('replicas', p.replicas, 1, 50, true),
        ...within('maxBatchSize', p.maxBatchSize, 1, Infinity, true),
        ...within('maxBatchTokens', p.maxBatchTokens, 1, Infinity, true),
        ...within('maxOutputTokensReserve', p.maxOutputTokensReserve, 1, Infinity, true),
        ...(s.enabled
          ? [
              ...within('speculative.draftTokens', s.draftTokens, 1, Infinity, true),
              ...within('speculative.acceptanceRate', s.acceptanceRate, 0, 1),
              ...within('speculative.draftStepMs', s.draftStepMs, 0),
            ]
          : []),
      ]
    }
  }
}
