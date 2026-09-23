import type { NodeKind } from '../types/contracts'
import { level } from './format'

// How load looks on the canvas (§11.3). Every color is a theme token.

/** Kinds with no capacity limit report 0% utilization, so they get no load color or percentage. */
export const hasCapacity = (kind: NodeKind) => kind === 'service' || kind === 'database' || kind === 'llm'

/** Node border: the same olive / orange / rust bands as the Load tab, so the canvas and the bars agree. */
export const loadColor = (util: number) => `var(--${level(util)})`

/** Soft outer glow in the load color that grows and strengthens with utilization. */
export function loadGlow(util: number): string {
  const u = Math.min(1, Math.max(0, util))
  return `0 0 ${Math.round(4 + 14 * u)}px ${Math.round(1 + 3 * u)}px color-mix(in srgb, ${loadColor(util)} ${Math.round(20 + 45 * u)}%, transparent)`
}

/** §11.3's clamp(round(rps / scale), 1, 8), scaled so the busiest edge of the run gets 8. No traffic, no dots. */
export function dotCount(rps: number, peakRps: number): number {
  if (!(rps > 0)) return 0
  return Math.min(8, Math.max(1, Math.round((rps / (peakRps || rps)) * 8)))
}

/** Seconds for a dot to cross its edge: 3 s for a trickle, 0.8 s at the run's peak. In 0.2 s steps, so
 *  playback doesn't restart the animation on every tiny change. */
export function dotSeconds(rps: number, peakRps: number): number {
  const s = 3 - 2.2 * Math.min(1, rps / (peakRps || 1))
  return Math.round(s * 5) / 5
}
