// How many requests a run will send (plan §3): the area under the arrival-rate curve,
// computed from the traffic profile instead of by simulating. The backend mirrors this
// in Step 12 to reject oversized runs with a 422, so keep the formulas identical.

import type { Design, TrafficProfile } from '../types/contracts'

/** Seconds of `[startS, startS + lengthS)` that fall inside `[0, durationS)`. */
function overlapS(startS: number, lengthS: number, durationS: number): number {
  return Math.max(0, Math.min(startS + lengthS, durationS) - startS)
}

/** Arrival rate (req/s) of one users node at second `s` of a run lasting `durationS`. */
export function rateAt(t: TrafficProfile, s: number, durationS: number): number {
  if (t.type === 'constant') return t.rps
  if (t.type === 'spike') return s >= t.peakStartS && s < t.peakStartS + t.peakDurationS ? t.peakRps : t.baseRps
  return t.startRps + ((t.endRps - t.startRps) * s) / durationS
}

/** Requests one users node sends over a run of `durationS` seconds. */
export function estimateRequests(traffic: TrafficProfile, durationS: number): number {
  switch (traffic.type) {
    case 'constant':
      // Rectangle.
      return traffic.rps * durationS
    case 'ramp':
      // Trapezoid: a straight line has the area of its average height.
      return ((traffic.startRps + traffic.endRps) / 2) * durationS
    case 'spike': {
      // Base rectangle over the whole run, plus the extra rate for the part of the
      // peak window inside it — the peak may start after the run ends, or outlast it.
      const peakS = overlapS(traffic.peakStartS, traffic.peakDurationS, durationS)
      return traffic.baseRps * durationS + (traffic.peakRps - traffic.baseRps) * peakS
    }
  }
}

/** Requests a whole design sends: the sum over its users nodes (§7.6 allows more than one). */
export function estimateDesignRequests(design: Design, durationS: number): number {
  return design.nodes.reduce(
    (total, node) => (node.kind === 'users' ? total + estimateRequests(node.params.traffic, durationS) : total),
    0,
  )
}
