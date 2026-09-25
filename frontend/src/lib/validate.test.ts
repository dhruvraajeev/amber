import { describe, expect, it } from 'vitest'
import type { Design, RunConfig } from '../api/api'
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

  it('refuses a self-hosted model too big for its GPU, with the same words as the backend', () => {
    const f = Object.entries(fixtures).find(([file]) => file.endsWith('model-does-not-fit.json'))![1]
    expect(validate(f.design)).toEqual([{
      code: 'PARAM_RANGE', nodeId: 'llm', path: 'params.gpuPresetId',
      message: 'LLM: the model does not fit on this GPU (16.1 GB of weights, 14.4 GB usable on the NVIDIA T4).',
    }])
    const q4 = structuredClone(f.design)
    const llm = q4.nodes.find((n) => n.id === 'llm')!
    if (llm.kind === 'llm' && llm.params.mode === 'selfHosted') llm.params.modelPresetId = 'llama-3.1-8b-instruct-q4km'
    expect(validate(q4)).toEqual([]) // 4.9 GB of quantized weights fit
  })

  it('refuses an output reserve smaller than what callers ask for, with the same words as the backend', () => {
    const f = Object.entries(fixtures).find(([file]) => file.endsWith('reserve-below-output.json'))![1]
    expect(validate(f.design)).toEqual([{
      code: 'PARAM_RANGE', nodeId: 'llm', path: 'params.maxOutputTokensReserve',
      message: 'LLM: the output reserve (512 tokens) is smaller than the 600 tokens Agent asks for per call. Raise maxOutputTokensReserve to at least 600.',
    }])
    const d = structuredClone(f.design)
    const agent = d.nodes.find((n) => n.id === 'agent')!
    const llm = d.nodes.find((n) => n.id === 'llm')!
    if (llm.kind === 'llm' && llm.params.mode === 'selfHosted') llm.params.maxOutputTokensReserve = 600
    expect(validate(d)).toEqual([]) // exactly enough is enough
    if (agent.kind === 'agent') agent.params.outputTokensPerCall = 100
    if (llm.kind === 'llm' && llm.params.mode === 'selfHosted') llm.params.maxOutputTokensReserve = 200
    expect(validate(d)).toEqual([])
    const tool = { id: 'e_agent_tool', source: 'agent', target: 'llm', role: 'tool' as const }
    expect(validate({ ...d, edges: [...d.edges, tool] })[0].message).toContain('256 tokens the model writes by default for calls from Agent')
    d.edges.push({ id: 'e_api_llm', source: 'api', target: 'llm' }, { id: 'e_agent_tool', source: 'agent', target: 'llm', role: 'tool' })
    expect(validate(d).map((i) => i.message)).toEqual([
      'LLM: the output reserve (200 tokens) is smaller than the 256 tokens the model writes by default for calls from api. Raise maxOutputTokensReserve to at least 256.',
    ])
  })

  it('treats an emptied number field (NaN) as out of range', () => {
    const f = Object.entries(fixtures).find(([file]) => file.endsWith('valid.json'))![1]
    const d = structuredClone(f.design)
    const api = d.nodes.find((n) => n.id === 'api')!
    if (api.kind === 'service') api.params.replicas = NaN
    expect(validate(d).map((i) => i.path)).toEqual(['params.replicas'])
  })
})
