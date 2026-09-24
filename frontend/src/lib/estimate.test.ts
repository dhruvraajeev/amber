import { describe, expect, it } from 'vitest'
import classicWebApp from '@shared/templates/classic-web-app.json'
import type { Design, TrafficProfile } from '../api/api'
import { estimateDesignRequests, estimateRequests } from './estimate'

// 10 rps everywhere, +100 rps between 20 s and 30 s.
const spike: TrafficProfile = { type: 'spike', baseRps: 10, peakRps: 110, peakStartS: 20, peakDurationS: 10 }

describe('estimateRequests', () => {
  it('constant: rate × duration', () => {
    expect(estimateRequests({ type: 'constant', rps: 100 }, 60)).toBe(6000)
  })

  it('ramp: average rate × duration', () => {
    expect(estimateRequests({ type: 'ramp', startRps: 0, endRps: 100 }, 60)).toBe(3000)
  })

  it('spike inside the run: whole peak counts', () => {
    expect(estimateRequests(spike, 60)).toBe(10 * 60 + 100 * 10)
  })

  it('spike cut off by the end of the run: only the overlap counts', () => {
    expect(estimateRequests(spike, 25)).toBe(10 * 25 + 100 * 5)
  })

  it('spike starting after the run ends: base only', () => {
    expect(estimateRequests(spike, 15)).toBe(10 * 15)
  })
})

describe('estimateDesignRequests', () => {
  const design = classicWebApp as Design

  it('sums the users nodes of a template', () => {
    expect(estimateDesignRequests(design, 60)).toBe(12000) // one users node at 200 rps
  })

  it('ignores nodes that carry no traffic', () => {
    expect(estimateDesignRequests({ ...design, nodes: design.nodes.filter((n) => n.kind !== 'users') }, 60)).toBe(0)
  })
})
