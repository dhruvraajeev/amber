import { describe, expect, it } from 'vitest'
import { configDiff, delta, METRICS } from './metrics'

const metric = (name: string) => METRICS.find((m) => m.name === name)!

describe('compare deltas', () => {
  it('knows lower latency and higher throughput are better', () => {
    expect(delta(metric('Latency p99'), 200, 100)).toEqual({ abs: -100, rel: -0.5, verdict: 'better' })
    expect(delta(metric('Latency p99'), 100, 200).verdict).toBe('worse')
    expect(delta(metric('Throughput'), 100, 120).verdict).toBe('better')
    expect(delta(metric('Monthly cost'), 100, 120).verdict).toBe('worse')
  })

  it('treats tiny changes as the same and survives a zero baseline', () => {
    expect(delta(metric('Latency p50'), 1000, 1002).verdict).toBe('same')
    expect(delta(metric('Error rate'), 0, 0)).toEqual({ abs: 0, rel: null, verdict: 'same' })
    expect(delta(metric('Error rate'), 0, 0.02)).toMatchObject({ rel: null, verdict: 'worse' })
  })
})

describe('config diff', () => {
  it('lists the settings that differ', () => {
    const a = { durationS: 60, seed: 42, warmupS: 5 }
    expect(configDiff(a, { ...a })).toEqual([])
    expect(configDiff(a, { ...a, seed: 7, durationS: 120 })).toEqual(['durationS', 'seed'])
  })
})
