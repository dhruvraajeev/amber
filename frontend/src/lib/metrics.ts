import type { RunConfig, RunResult } from '../api/api'
import { ms, pct, rps, usd } from './format'

// The headline metrics Compare shows, and which direction counts as better for each.

export interface Metric {
  name: string
  get: (r: RunResult) => number | undefined // undefined when a run doesn't have it (TTFT without an LLM)
  format: (v: number) => string
  formatDelta?: (v: number) => string // when "+2%" would read as a relative change
  better: 'lower' | 'higher'
}

export const METRICS: Metric[] = [
  { name: 'Latency p50', get: (r) => r.summary.latencyMs.p50, format: ms, better: 'lower' },
  { name: 'Latency p95', get: (r) => r.summary.latencyMs.p95, format: ms, better: 'lower' },
  { name: 'Latency p99', get: (r) => r.summary.latencyMs.p99, format: ms, better: 'lower' },
  { name: 'Time to first token p50', get: (r) => r.summary.ttftMs?.p50, format: ms, better: 'lower' },
  { name: 'Throughput', get: (r) => r.summary.throughputRps, format: rps, better: 'higher' },
  { name: 'Error rate', get: (r) => r.summary.errorRate, format: (v) => pct(v, 1), formatDelta: (v) => `${(v * 100).toFixed(1)} pts`, better: 'lower' },
  { name: 'Monthly cost', get: (r) => r.cost.monthlyTotalUsd, format: usd, better: 'lower' },
]

export type Verdict = 'better' | 'worse' | 'same'

/** B relative to A: the absolute and relative change, and whether that's good. Under 0.5% counts as the same. */
export function delta(m: Metric, a: number, b: number): { abs: number; rel: number | null; verdict: Verdict } {
  const abs = b - a
  const rel = a === 0 ? null : abs / Math.abs(a)
  const tiny = rel === null ? abs === 0 : Math.abs(rel) < 0.005
  const verdict = tiny ? 'same' : (abs < 0) === (m.better === 'lower') ? 'better' : 'worse'
  return { abs, rel, verdict }
}

/** The run settings that differ between two runs; comparing designs only makes sense when this is empty. */
export function configDiff(a: RunConfig, b: RunConfig): (keyof RunConfig)[] {
  return (['durationS', 'seed', 'warmupS'] as const).filter((k) => a[k] !== b[k])
}
