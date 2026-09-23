import { describe, expect, it } from 'vitest'
import agent from '@shared/templates/agent-self-hosted.json'
import classic from '@shared/templates/classic-web-app.json'
import rag from '@shared/templates/rag-chatbot-hosted.json'
import { designHash } from '../canvas/map'
import type { Design, RunConfig, ServiceParams } from '../types/contracts'
import { fakeResult } from './fake'

const config: RunConfig = { durationS: 60, seed: 42, warmupS: 5 }
const run = async (design: Design, c = config) => fakeResult(design, c, await designHash(design))

// The classic template with its API squeezed to 2 workers per replica, so load is visible.
const withApi = (replicas: number): Design => {
  const d = structuredClone(classic) as Design
  const api = d.nodes.find((n) => n.id === 'n_api')!
  Object.assign(api.params as ServiceParams, { replicas, concurrencyPerReplica: 2 })
  return d
}

describe('fake simulate', () => {
  it('is deterministic: same design, config and seed → identical result', async () => {
    for (const t of [classic, rag, agent] as Design[]) expect(await run(t)).toEqual(await run(structuredClone(t)))
  })

  it('a different seed gives a different result', async () => {
    expect(await run(classic as Design, { ...config, seed: 7 })).not.toEqual(await run(classic as Design))
  })

  it('more replicas → lower utilization and lower p99', async () => {
    const [few, many] = [await run(withApi(2)), await run(withApi(6))]
    const util = (r: typeof few) => r.nodes.find((n) => n.id === 'n_api')!.utilAvg
    expect(util(many)).toBeLessThan(util(few))
    expect(many.summary.latencyMs.p99).toBeLessThan(few.summary.latencyMs.p99)
  })

  it('an overloaded service rejects requests and is reported', async () => {
    const r = await run(withApi(1))
    expect(r.summary.rejected).toBeGreaterThan(0)
    expect(r.bottlenecks[0]).toMatchObject({ severity: 'critical', nodeId: 'n_api' })
  })

  it('fills every part of the §7.4 result sensibly', async () => {
    const r = await run(agent as Design, { durationS: 600, seed: 1, warmupS: 5 })
    expect(r.timeline.length).toBeLessThanOrEqual(300)
    expect(r.gpu).toHaveLength(1)
    expect(r.summary.ttftMs).toBeDefined()
    expect(r.engine.wallMs).toBeGreaterThanOrEqual(400)
    expect(r.engine.wallMs).toBeLessThanOrEqual(900)
    expect(r.attribution.reduce((s, a) => s + a.queueShare + a.workShare, 0)).toBeCloseTo(1)
    expect(r.cost.monthlyTotalUsd).toBe(r.cost.breakdown.reduce((s, b) => s + b.usd, 0))
    expect(r.cost.assumptions.join(' ')).toContain('repeats all month')
    const { p50, p95, p99 } = r.summary.latencyMs
    expect(p50).toBeGreaterThan(0)
    expect(p50 <= p95 && p95 <= p99).toBe(true)
  })
})
