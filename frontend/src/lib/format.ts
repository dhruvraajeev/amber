// Number formatting for results. Every metric carries its unit; render them inside `.num`
// (mono, tabular figures) so columns of numbers line up.

const grouped = (v: number, digits = 0) =>
  v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })

/** 42 ms · 1,240 ms · 12.5 s */
export const ms = (v: number) => (v >= 10_000 ? `${grouped(v / 1000, 1)} s` : `${grouped(v)} ms`)

/** A 0..1 share as a percentage: 0.923 → "92%". */
export const pct = (v: number, digits = 0) => `${(v * 100).toFixed(digits)}%`

/** $0.42 · $38 · $4,210 */
export const usd = (v: number) => `$${grouped(v, v > 0 && v < 10 ? 2 : 0)}`

/** 4.5 req/s · 200 req/s */
export const rps = (v: number) => `${grouped(v, v > 0 && v < 10 ? 1 : 0)} req/s`

/** 12,000 */
export const count = (v: number) => grouped(v)

/** Load level for a utilization, with §11.3's thresholds: olive < 0.6 ≤ orange < 0.85 ≤ rust. */
export type Level = 'ok' | 'warn' | 'crit'
export const level = (util: number): Level => (util >= 0.85 ? 'crit' : util >= 0.6 ? 'warn' : 'ok')
