import { describe, expect, it } from 'vitest'
import type {
  DatabasePreset,
  Design,
  GpuPreset,
  HostedLlmPreset,
  LlmParams,
  ModelPreset,
  NodeKind,
  NodeParamsByKind,
  ServicePreset,
  TrafficProfile,
} from './contracts'
import gpus from '@shared/presets/gpus.json'
import models from '@shared/presets/models.json'
import hostedLlms from '@shared/presets/hosted_llms.json'
import databases from '@shared/presets/databases.json'
import services from '@shared/presets/services.json'

// JSON imports widen literals to `string`, so tsc can't check templates directly.
// Instead: one exemplar per shape, type-checked here, and every template must match its exemplar's
// keys and value types exactly (no missing fields, no extra fields, no `p50` instead of `p50Ms`).
const dist = { p50Ms: 1, p99Ms: 2 }
const traffic: { [T in TrafficProfile['type']]: Extract<TrafficProfile, { type: T }> } = {
  constant: { type: 'constant', rps: 1 },
  spike: { type: 'spike', baseRps: 1, peakRps: 2, peakStartS: 0, peakDurationS: 1 },
  ramp: { type: 'ramp', startRps: 1, endRps: 2 },
}
const llm: { [M in LlmParams['mode']]: Extract<LlmParams, { mode: M }> } = {
  hosted: {
    mode: 'hosted', presetId: '', ttft: dist, tokensPerSecond: { p50: 1, p99Low: 1 },
    inputUsdPer1M: 0, outputUsdPer1M: 0, rateLimitRpm: 1, maxRetries: 0,
  },
  selfHosted: {
    mode: 'selfHosted', gpuPresetId: '', modelPresetId: '', profileId: '', replicas: 1,
    maxBatchSize: 1, maxBatchTokens: 1, maxOutputTokensReserve: 1,
    speculative: { enabled: false, draftTokens: 1, acceptanceRate: 0.5, draftStepMs: 1 },
  },
}
const exemplar: { [K in NodeKind]: (p: Record<string, unknown>) => NodeParamsByKind[K] } = {
  users: (p) => ({ traffic: traffic[(p.traffic as TrafficProfile).type], clientTimeoutMs: 1 }),
  loadBalancer: () => ({ algorithm: 'roundRobin', overhead: dist }),
  service: () => ({ replicas: 1, concurrencyPerReplica: 1, queueLimit: 0, work: dist, costPerReplicaMonth: 0 }),
  cache: () => ({ hitRate: 0.5, latency: dist, costPerMonth: 0 }),
  database: () => ({ preset: 'postgres', connectionPool: 1, queueLimit: 0, query: dist, costPerMonth: 0 }),
  agent: () => ({
    llmCallsMean: 1, toolCallsPerStep: 0, toolLatency: dist,
    basePromptTokens: 1, contextGrowthTokensPerStep: 0, outputTokensPerCall: 1,
  }),
  llm: (p) => llm[p.mode as LlmParams['mode']],
}

// Enum fields the shape check can't see (it only compares typeof).
const enums: Record<string, readonly string[]> = {
  algorithm: ['roundRobin', 'leastConnections'],
  preset: ['postgres', 'mongodb', 'vector', 'custom'],
}

// Returns a list of mismatches between `actual` and `expected` (same keys, same value types).
function shapeDiff(actual: unknown, expected: unknown, path = ''): string[] {
  if (typeof expected !== 'object' || expected === null) {
    const bad = typeof actual !== typeof expected
    const key = path.split('.').pop()!
    if (!bad && key in enums && !enums[key].includes(actual as string)) return [`${path}: bad value ${actual}`]
    return bad ? [`${path}: expected ${typeof expected}, got ${typeof actual}`] : []
  }
  if (typeof actual !== 'object' || actual === null) return [`${path}: expected object`]
  const a = actual as Record<string, unknown>
  const e = expected as Record<string, unknown>
  const keys = new Set([...Object.keys(a), ...Object.keys(e)])
  return [...keys].flatMap((k) =>
    !(k in e) ? [`${path}.${k}: unknown field`] : !(k in a) ? [`${path}.${k}: missing`] : shapeDiff(a[k], e[k], `${path}.${k}`),
  )
}

const templates = import.meta.glob<Design>('@shared/templates/*.json', { eager: true, import: 'default' })
const presetIds = {
  presetId: hostedLlms.map((p) => p.id),
  gpuPresetId: gpus.map((p) => p.id),
  modelPresetId: models.map((p) => p.id),
}

describe('starter templates match the §7 contracts', () => {
  it('finds all three templates', () => {
    expect(Object.keys(templates).map((f) => f.split('/').pop()).sort()).toEqual([
      'agent-self-hosted.json',
      'classic-web-app.json',
      'rag-chatbot-hosted.json',
    ])
  })

  for (const [file, design] of Object.entries(templates)) {
    it(file.split('/').pop()!, () => {
      expect(Object.keys(design).sort()).toEqual(['edges', 'name', 'nodes', 'version'])
      expect(design.version).toBe(1)

      const ids = new Set(design.nodes.map((n) => n.id))
      expect(ids.size).toBe(design.nodes.length)
      for (const n of design.nodes) {
        expect(Object.keys(exemplar)).toContain(n.kind)
        const { params: _, ...rest } = n
        expect(shapeDiff(rest, { id: '', kind: '', label: '', position: { x: 0, y: 0 } }, n.id)).toEqual([])
        const params = n.params as unknown as Record<string, unknown>
        expect(shapeDiff(params, exemplar[n.kind](params), n.id)).toEqual([])
        for (const [field, known] of Object.entries(presetIds)) {
          if (field in params) expect(known, `${n.id}.${field}`).toContain(params[field])
        }
      }
      for (const e of design.edges) {
        expect(ids.has(e.source) && ids.has(e.target), e.id).toBe(true)
        if (e.role !== undefined) expect(['llm', 'tool']).toContain(e.role)
      }
    })
  }
})

describe('presets', () => {
  // Assigning to the typed arrays is the compile-time check; the loop is the runtime one.
  const all: Record<string, { id: string; verifiedAt: string | null }[]> = {
    gpus: gpus satisfies GpuPreset[],
    models: models satisfies ModelPreset[],
    hostedLlms: hostedLlms satisfies HostedLlmPreset[],
    databases: databases as DatabasePreset[],
    services: services satisfies ServicePreset[],
  }

  it('every preset is unverified (verifiedAt: null) with a unique id', () => {
    for (const [name, list] of Object.entries(all)) {
      expect(list.length, name).toBeGreaterThan(0)
      expect(new Set(list.map((p) => p.id)).size, name).toBe(list.length)
      for (const p of list) expect(p.verifiedAt, `${name}/${p.id}`).toBeNull()
    }
  })

  it('database presets use a known preset kind', () => {
    for (const d of databases) expect(enums.preset).toContain(d.preset)
  })
})
