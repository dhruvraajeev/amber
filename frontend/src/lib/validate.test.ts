import { describe, expect, it } from 'vitest'
import type { Design, RunConfig } from '../types/contracts'
import { RULE_CODES, validate } from './validate'

// Each fixture lists the exact set of codes it must produce. The backend (Step 12) runs the same files.
interface Fixture { description: string; expect: string[]; config: RunConfig; design: Design }
const fixtures = import.meta.glob<Fixture>('@shared/fixtures/graph/*.json', { eager: true, import: 'default' })
const templates = import.meta.glob<Design>('@shared/templates/*.json', { eager: true, import: 'default' })
const codes = (d: Design, c?: RunConfig) => [...new Set(validate(d, c).map((i) => i.code))].sort()

describe('graph fixtures', () => {
  for (const [file, f] of Object.entries(fixtures))
    it(`${file.split('/').pop()}: ${f.description}`, () => expect(codes(f.design, f.config)).toEqual([...f.expect].sort()))

  it('every rule code has a failing fixture', () => {
    const covered = new Set(Object.values(fixtures).flatMap((f) => f.expect))
    expect(RULE_CODES.filter((c) => !covered.has(c))).toEqual([])
  })
})

describe('validate', () => {
  it('starter templates are valid', () => {
    for (const t of Object.values(templates)) expect(codes(t, { durationS: 60, seed: 1, warmupS: 5 }), t.name).toEqual([])
  })

  it('points p99 < p50 at the field, so the inspector can show it inline', () => {
    const f = Object.entries(fixtures).find(([file]) => file.endsWith('param-range.json'))![1]
    expect(validate(f.design)).toEqual([expect.objectContaining({ code: 'PARAM_RANGE', nodeId: 'api', path: 'params.work' })])
  })

  it('treats an emptied number field (NaN) as out of range', () => {
    const f = Object.entries(fixtures).find(([file]) => file.endsWith('valid.json'))![1]
    const d = structuredClone(f.design)
    const api = d.nodes.find((n) => n.id === 'api')!
    if (api.kind === 'service') api.params.replicas = NaN
    expect(validate(d).map((i) => i.path)).toEqual(['params.replicas'])
  })
})
