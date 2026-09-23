// The phase-0 stand-in for the simulator (§11.5). Not a simulation: a few lines of queueing
// arithmetic per node, so results respond sensibly to edits (more replicas → lower utilization
// and p99). Deterministic: every random draw comes from mulberry32 seeded by config.seed and
// the design hash, never Math.random(). Deleted when api.ts switches to the backend (phase 2).

import gpus from '@shared/presets/gpus.json'
import hostedLlms from '@shared/presets/hosted_llms.json'
import models from '@shared/presets/models.json'
import { designHash } from '../canvas/map'
import { rateAt } from '../lib/estimate'
import type { Design, DesignEdge, DesignNode, LatencyDist, RunConfig, RunResult, TimelinePoint } from '../types/contracts'

export async function fakeSimulate(design: Design, config: RunConfig): Promise<RunResult> {
  const result = fakeResult(design, config, await designHash(design))
  // The artificial 400–900 ms delay, so loading states get built. It doubles as `wallMs`.
  await new Promise((resolve) => setTimeout(resolve, result.engine.wallMs))
  return result
}

// ponytail: fixed self-hosted timing until calibration profiles exist (Step 22 reads shared/profiles).
const DECODE_STEP_MS = 25
const SELF_TTFT_MS = 150
const MAX_POINTS = 300 // §7.4 timeline cap

type Dist = [p50: number, p99: number]
type ErrorKind = 'rejected' | 'rateLimited'

/** The one-number-per-node shape of each kind that the arithmetic below needs. */
interface NodeModel {
  own: Dist // ms of the node's own work per visit
  calls: number[] // expected calls per visit along each outgoing edge, in edge order
  capacity: (holdMs: number) => number // req/s it can serve; Infinity if unbounded
  slots: number // requests it serves at once (threads, connections, batch slots)
  holds: boolean // keeps its slot while downstream calls run (thread-per-request service)
  queueCap: number // waiting requests before it turns traffic away
  error?: ErrorKind // what happens to traffic beyond capacity
  ttft?: Dist // LLMs: time to first token
}

/** Per node, per timeline point. */
interface NodeStat { util: number; queue: number; rejects: number; queue99: number; visits: number }

/** One timeline point plus the internals the summary is built from. */
interface Point { point: TimelinePoint; stats: Map<string, NodeStat>; errors: Record<ErrorKind, number>; timeouts: number; ttft?: Dist }

export function fakeResult(design: Design, config: RunConfig, hash: string): RunResult {
  const rng = mulberry32((config.seed ^ parseInt(hash.slice(0, 8), 16)) >>> 0)
  const jitter = (spread: number) => 1 + (rng() - 0.5) * spread
  const wallMs = Math.round(400 + rng() * 500)

  const out = new Map(design.nodes.map((n) => [n.id, [] as DesignEdge[]]))
  for (const e of design.edges) out.get(e.source)?.push(e)
  const order = topoOrder(design.nodes, out)
  const model = new Map(order.map((n) => [n.id, describe(n, out.get(n.id)!)]))
  const users = order.filter((n) => n.kind === 'users')
  const timeoutMs = Math.min(...users.map((n) => n.params.clientTimeoutMs))
  const firstLlm = order.find((n) => n.kind === 'llm')
  const llmModel = firstLlm && model.get(firstLlm.id)!
  const step = Math.ceil(config.durationS / MAX_POINTS) // seconds per timeline point

  const points: Point[] = []
  for (let t = 0; t < config.durationS; t += step) {
    // Forward: requests per second arriving at each node.
    const rate = new Map<string, number>()
    for (const n of order) {
      const r = n.kind === 'users' ? rateAt(n.params.traffic, t + step / 2, config.durationS) * jitter(0.1) : (rate.get(n.id) ?? 0)
      rate.set(n.id, r)
      out.get(n.id)!.forEach((e, i) => rate.set(e.target, (rate.get(e.target) ?? 0) + r * model.get(n.id)!.calls[i]))
    }
    const arrivals = users.reduce((s, n) => s + rate.get(n.id)!, 0)

    // Backward: latency per visit, children first, since a service's slot is held during its downstream calls.
    const latency = new Map<string, Dist>()
    const stats = new Map<string, NodeStat>()
    const errors = { rejected: 0, rateLimited: 0 }
    for (const n of [...order].reverse()) {
      const m = model.get(n.id)!
      const r = rate.get(n.id)!
      const down = [0, 1].map((k) => out.get(n.id)!.reduce((s, e, i) => s + m.calls[i] * (latency.get(e.target)?.[k] ?? 0), 0))
      const hold = [0, 1].map((k) => m.own[k] + (m.holds ? down[k] : 0))
      const util = r / m.capacity(hold[0])
      const queue = hold.map((h) => h * waitFactor(util, m.slots))
      latency.set(n.id, [0, 1].map((k) => m.own[k] + down[k] + queue[k]) as Dist)
      const rejects = util > 1 && m.error ? r * (1 - 1 / util) : 0
      if (m.error) errors[m.error] += rejects
      stats.set(n.id, {
        util,
        // Little's law (waiting = rate × wait time), or a full queue once saturated.
        queue: util >= 1 && m.queueCap < Infinity ? m.queueCap : Math.min(m.queueCap, (r * queue[0]) / 1000),
        rejects,
        queue99: queue[1],
        visits: arrivals ? r / arrivals : 0,
      })
    }

    const noise = jitter(0.06)
    const perRequest = (k: 0 | 1) => (arrivals ? users.reduce((s, n) => s + rate.get(n.id)! * latency.get(n.id)![k], 0) / arrivals : 0) * noise
    const { p50, p95, p99 } = spread(perRequest(0), perRequest(1))
    const failed = arrivals ? Math.min(1, (errors.rejected + errors.rateLimited) / arrivals) : 0
    const timedOut = (1 - failed) * (p50 > timeoutMs ? 0.5 : p95 > timeoutMs ? 0.05 : p99 > timeoutMs ? 0.01 : 0)
    const errorRate = failed + timedOut
    const llmUtil = firstLlm && stats.get(firstLlm.id)!.util
    points.push({
      point: {
        t, arrivalsRps: arrivals, throughputRps: arrivals * (1 - errorRate), errorRate, p50, p95, p99,
        nodes: Object.fromEntries([...stats].map(([id, s]) => [id, { util: s.util, queue: s.queue, rejects: s.rejects, throughputRps: rate.get(id)! - s.rejects }])),
      },
      stats, errors, timeouts: arrivals * timedOut,
      ttft: llmModel && (llmModel.ttft!.map((x) => x * (1 + waitFactor(llmUtil!, llmModel.slots))) as Dist),
    })
  }

  // Summary stats skip the warmup (§7.3); the timeline keeps it.
  const kept = points.filter((p) => p.point.t >= config.warmupS)
  const measured = kept.length ? kept : points
  const total = (f: (p: Point) => number) => measured.reduce((s, p) => s + f(p) * step, 0)
  const requests = Math.round(total((p) => p.point.arrivalsRps))
  const rejected = Math.round(total((p) => p.errors.rejected))
  const rateLimited = Math.round(total((p) => p.errors.rateLimited))
  const timeouts = Math.round(total((p) => p.timeouts))
  const completed = Math.max(0, requests - rejected - rateLimited - timeouts)
  const col = (f: (p: Point) => number) => measured.map(f)
  const p99s = col((p) => p.point.p99)
  // Calls served per second over the whole run: what a hosted LLM bills for.
  const servedRps = (id: string) => mean(points.map((p) => p.point.nodes[id]?.throughputRps ?? 0))
  const costs = design.nodes.map((n) => ({ nodeId: n.id, ...monthlyCost(n, servedRps(n.id)) }))
  const nodes = design.nodes.map((n) => {
    const util = col((p) => p.stats.get(n.id)?.util ?? 0)
    const queue = col((p) => p.stats.get(n.id)?.queue ?? 0)
    return {
      id: n.id, kind: n.kind, utilAvg: mean(util), utilMax: Math.max(...util), queueAvg: mean(queue), queueMax: Math.max(...queue),
      rejects: Math.round(total((p) => p.stats.get(n.id)?.rejects ?? 0)), monthlyUsd: costs.find((c) => c.nodeId === n.id)!.usd,
    }
  })
  // KV use and batch size both track utilization; whatever doesn't fit waits.
  const gpu = design.nodes.flatMap((n) => {
    if (n.kind !== 'llm' || n.params.mode !== 'selfHosted') return []
    const maxBatch = n.params.maxBatchSize
    return [{ nodeId: n.id, points: points.map(({ point, stats }) => {
      const s = stats.get(n.id)!
      return { t: point.t, kvPct: Math.min(1, 0.9 * s.util), batch: Math.round(Math.min(1, s.util) * maxBatch), waiting: Math.round(s.queue) }
    }) }]
  })
  const monthlyTotalUsd = costs.reduce((s, c) => s + c.usd, 0)
  const summaryP99 = pct(p99s, 0.99)

  return {
    designHash: hash,
    config,
    engine: { events: requests * design.nodes.length * 2, wallMs, eventsPerSec: Math.round((requests * design.nodes.length * 2) / (wallMs / 1000)), simulatedRequests: requests },
    summary: {
      requests, completed, errors: rejected + rateLimited, timeouts, rejected,
      throughputRps: completed / (measured.length * step), errorRate: requests ? (requests - completed) / requests : 0,
      latencyMs: { p50: pct(col((p) => p.point.p50), 0.5), p95: pct(col((p) => p.point.p95), 0.95), p99: summaryP99, max: Math.max(...p99s) * 1.3 },
      ...(llmModel && { ttftMs: spread(pct(col((p) => p.ttft![0]), 0.5), pct(col((p) => p.ttft![1]), 0.99)) }),
    },
    timeline: points.map((p) => p.point),
    nodes,
    gpu,
    attribution: attribution(measured.reduce((a, b) => (b.point.p99 > a.point.p99 ? b : a)).stats, model),
    cost: {
      monthlyTotalUsd,
      breakdown: costs.filter((c) => c.usd > 0).map(({ nodeId, usd, detail }) => ({ nodeId, usd, detail })),
      assumptions: [
        'Hosted LLM cost assumes the simulated traffic pattern repeats all month (30 days).',
        'Demo data: a rough built-in estimate, not the simulator.',
        'Preset prices are unverified estimates.',
      ],
    },
    bottlenecks: bottlenecks(design, nodes, gpu, summaryP99),
  }
}

function describe(n: DesignNode, out: DesignEdge[]): NodeModel {
  const base: NodeModel = { own: [0, 0], calls: out.map(() => 1), capacity: () => Infinity, slots: 1, holds: false, queueCap: Infinity }
  const d = (l: LatencyDist): Dist => [l.p50Ms, l.p99Ms]
  switch (n.kind) {
    case 'users':
      return base
    case 'loadBalancer':
      return { ...base, own: d(n.params.overhead), calls: out.map(() => 1 / out.length) }
    case 'service': {
      const p = n.params
      const capacity = (holdMs: number) => (p.replicas * p.concurrencyPerReplica * 1000) / holdMs
      const slots = p.replicas * p.concurrencyPerReplica
      return { ...base, own: d(p.work), holds: true, capacity, slots, queueCap: p.queueLimit * p.replicas, error: 'rejected' }
    }
    case 'cache':
      return { ...base, own: d(n.params.latency), calls: out.map(() => 1 - n.params.hitRate) }
    case 'database': {
      const p = n.params
      const capacity = () => (p.connectionPool * 1000) / p.query.p50Ms
      return { ...base, own: d(p.query), capacity, slots: p.connectionPool, queueCap: p.queueLimit, error: 'rejected' }
    }
    case 'agent': {
      // §8.5: llmCallsMean LLM calls, with toolCallsPerStep tool calls between consecutive ones.
      const p = n.params
      const toolCalls = (p.llmCallsMean - 1) * p.toolCallsPerStep
      const tools = out.filter((e) => e.role === 'tool').length
      return {
        ...base,
        own: tools ? [0, 0] : (d(p.toolLatency).map((x) => x * toolCalls) as Dist),
        calls: out.map((e) => (e.role === 'llm' ? p.llmCallsMean : toolCalls / tools)),
      }
    }
    case 'llm': {
      const p = n.params
      if (p.mode === 'hosted') {
        const tokens = (hostedLlms.find((h) => h.id === p.presetId) ?? hostedLlms[0]).defaultOutputTokens
        const own: Dist = [p.ttft.p50Ms + (tokens / p.tokensPerSecond.p50) * 1000, p.ttft.p99Ms + (tokens / p.tokensPerSecond.p99Low) * 1000]
        // No concurrency cap (§8.6): nothing queues, traffic past the rate limit is turned away.
        return { ...base, own, ttft: d(p.ttft), capacity: () => p.rateLimitRpm / 60, slots: Infinity, error: 'rateLimited' }
      }
      const tokens = (models.find((m) => m.id === p.modelPresetId) ?? models[0]).defaultOutputTokens
      const own = SELF_TTFT_MS + tokens * DECODE_STEP_MS
      const capacity = () => (p.replicas * p.maxBatchSize * 1000) / DECODE_STEP_MS / tokens
      return { ...base, own: [own, 2 * own], ttft: [SELF_TTFT_MS, 2 * SELF_TTFT_MS], capacity, slots: p.replicas * p.maxBatchSize }
    }
  }
}

/** §8.10, with hosted token spend extrapolated from `rps` calls per second. */
function monthlyCost(n: DesignNode, rps: number): { usd: number; detail: string } {
  switch (n.kind) {
    case 'service':
      return { usd: n.params.replicas * n.params.costPerReplicaMonth, detail: `${plural(n.params.replicas, 'replica')} × $${n.params.costPerReplicaMonth}/mo` }
    case 'cache':
    case 'database':
      return { usd: n.params.costPerMonth, detail: 'flat monthly price' }
    case 'llm': {
      const p = n.params
      if (p.mode === 'selfHosted') {
        const gpu = gpus.find((g) => g.id === p.gpuPresetId) ?? gpus[0]
        return { usd: p.replicas * gpu.usdPerHour * 730, detail: `${p.replicas} × ${gpu.name} at $${gpu.usdPerHour}/h` }
      }
      const preset = hostedLlms.find((h) => h.id === p.presetId) ?? hostedLlms[0]
      const perCall = (preset.defaultPromptTokens * p.inputUsdPer1M + preset.defaultOutputTokens * p.outputUsdPer1M) / 1e6
      return { usd: perCall * rps * 2_592_000, detail: 'token spend at the simulated rate' }
    }
    default:
      return { usd: 0, detail: '' }
  }
}

/** Where the slowest moment's p99 time goes, split into waiting and working (shares total 1). */
function attribution(stats: Map<string, NodeStat>, model: Map<string, NodeModel>) {
  const rows = [...stats].map(([nodeId, s]) => ({ nodeId, queue: s.visits * s.queue99, work: s.visits * model.get(nodeId)!.own[1] }))
  const sum = rows.reduce((s, r) => s + r.queue + r.work, 0) || 1
  return rows
    .filter((r) => r.queue + r.work > 0)
    .sort((a, b) => b.queue + b.work - (a.queue + a.work))
    .map((r) => ({ nodeId: r.nodeId, queueShare: r.queue / sum, workShare: r.work / sum }))
}

/** §8.9's rules, simplified: at most one message per node, three overall, worst first. */
function bottlenecks(design: Design, nodes: RunResult['nodes'], gpu: RunResult['gpu'], p99: number): RunResult['bottlenecks'] {
  const found: RunResult['bottlenecks'] = []
  for (const s of nodes) {
    const n = design.nodes.find((x) => x.id === s.id)!
    const util = Math.round(s.utilAvg * 100)
    const kv = gpu.find((g) => g.nodeId === n.id)?.points
    const kvFull = kv ? kv.filter((p) => p.kvPct >= 0.95).length / kv.length : 0
    const at = (severity: 'warn' | 'critical', message: string) => found.push({ severity, nodeId: n.id, message })
    // Only hosted LLMs turn excess traffic away as rate limiting; services and databases reject it.
    if (s.rejects > 0 && n.kind === 'llm') at('warn', `${n.label} hit its rate limit ${s.rejects} times. Add retries/backoff or a higher tier.`)
    else if (s.rejects > 0) at('critical', `${n.label} rejected ${s.rejects} requests. Raise queueLimit or add capacity.`)
    else if (kvFull > 0.2) at('critical', `${n.label} GPU memory is full ${Math.round(kvFull * 100)}% of the time. Requests wait for KV cache space.`)
    else if (s.utilAvg >= 0.9) at('critical', `${n.label} is at ${util}% capacity. Requests queue for up to ${Math.round(s.queueMax)} waiting.`)
    else if (s.utilAvg >= 0.7) at('warn', `${n.label} is at ${util}%. There's little headroom for spikes.`)
  }
  found.sort((a, b) => (a.severity === b.severity ? 0 : a.severity === 'critical' ? -1 : 1))
  return found.length ? found.slice(0, 3) : [{ severity: 'info', message: `No bottlenecks at this traffic. p99 is ${Math.round(p99)} ms.` }]
}

/** Kahn's algorithm: sources first. Nodes on a cycle are left out (the validator rejects those designs). */
function topoOrder(nodes: DesignNode[], out: Map<string, DesignEdge[]>): DesignNode[] {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const incoming = new Map(nodes.map((n) => [n.id, 0]))
  for (const edges of out.values()) for (const e of edges) incoming.set(e.target, (incoming.get(e.target) ?? 0) + 1)
  const ready = nodes.filter((n) => incoming.get(n.id) === 0)
  const order: DesignNode[] = []
  for (let n = ready.shift(); n; n = ready.shift()) {
    order.push(n)
    for (const e of out.get(n.id)!) {
      incoming.set(e.target, incoming.get(e.target)! - 1)
      if (incoming.get(e.target) === 0 && byId.has(e.target)) ready.push(byId.get(e.target)!)
    }
  }
  return order
}

/** Tiny seeded PRNG: uniform [0, 1) from a 32-bit seed. */
function mulberry32(seed: number): () => number {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/**
 * Waiting time as a multiple of service time for `slots` servers at utilization `util`
 * (Sakasegawa's M/M/c approximation). With one slot it is util / (1 − util), i.e. §11.5's
 * `base / (1 − util)` minus the base itself; more slots absorb load far better. Utilization is
 * capped at 0.97 so a saturated node stays finite.
 */
function waitFactor(util: number, slots: number): number {
  const u = Math.min(util, 0.97)
  return u ** (Math.sqrt(2 * (slots + 1)) - 1) / (slots * (1 - u))
}

/** p95 isn't modeled separately: it sits 70% of the way from p50 to p99. */
const spread = (p50: number, p99: number) => ({ p50, p95: p50 + 0.7 * (p99 - p50), p99 })
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
const mean = (xs: number[]) => xs.reduce((s, x) => s + x, 0) / (xs.length || 1)
const pct = (xs: number[], q: number) => [...xs].sort((a, b) => a - b)[Math.min(xs.length - 1, Math.floor(q * xs.length))] ?? 0
