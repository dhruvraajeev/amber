import { describe, expect, it } from 'vitest'
import agentTemplate from '@shared/templates/agent-self-hosted.json'
import type { AgentParams } from '../api/api'
import { agentPerRequest, kvBudget } from './ai'

describe('kvBudget', () => {
  it('Llama 3.1 8B FP16 on an L4: 24 GB × 0.9 − 16.1 GB of weights, 2 × 32 layers × 8 heads × 128 × 2 bytes a token', () => {
    const kv = kvBudget('nvidia-l4-24gb', 'llama-3.1-8b-instruct-fp16')!
    expect(kv.capacityBytes).toBeCloseTo(5.5e9, -3)
    expect(kv.bytesPerToken).toBe(131_072) // 128 KiB
    expect(Math.floor(kv.capacityBytes / kv.bytesPerToken)).toBe(41_961)
  })

  it('is ≤ 0 when the weights leave nothing for the cache (the T4 check validation reports)', () => {
    expect(kvBudget('nvidia-t4-16gb', 'llama-3.1-8b-instruct-fp16')!.capacityBytes).toBeLessThanOrEqual(0)
    expect(kvBudget('nvidia-t4-16gb', 'llama-3.1-8b-instruct-q4km')!.capacityBytes).toBeGreaterThan(0)
  })

  it('is undefined for an unknown preset', () => {
    expect(kvBudget('nope', 'llama-3.1-8b-instruct-fp16')).toBeUndefined()
    expect(kvBudget('nvidia-l4-24gb', 'nope')).toBeUndefined()
  })
})

const agent = agentTemplate.nodes.find((n) => n.kind === 'agent')!.params as AgentParams

describe('agentPerRequest', () => {
  it('the agent template: 3 calls, 2 tool calls, 800 + 1,100 + … prompt tokens, 3 × 80 output', () => {
    // λ = 2: E[prompt] = 3 × 800 + 300 × (2λ + λ²) / 2 = 2,400 + 1,200.
    expect(agentPerRequest(agent)).toEqual({ llmCalls: 3, toolCalls: 2, promptTokens: 3600, outputTokens: 240 })
  })

  it('one call on average means exactly one call: no tools, no context growth', () => {
    expect(agentPerRequest({ ...agent, llmCallsMean: 1 })).toEqual({ llmCalls: 1, toolCalls: 0, promptTokens: 800, outputTokens: 80 })
  })

  it('matches the average of simulated requests (n = 1 + Poisson(mean − 1), call i sends base + i × growth)', () => {
    const p = { ...agent, llmCallsMean: 3.5, toolCallsPerStep: 2 }
    let seed = 7 // mulberry32: any fixed stream will do
    const random = () => {
      seed = (seed + 0x6d2b79f5) | 0
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
    const poisson = (λ: number) => { // Knuth, as sim/rng.py
      let [k, prod] = [0, random()]
      while (prod > Math.exp(-λ)) [k, prod] = [k + 1, prod * random()]
      return k
    }
    const N = 200_000
    const sum = { llmCalls: 0, toolCalls: 0, promptTokens: 0, outputTokens: 0 }
    for (let r = 0; r < N; r++) {
      const n = 1 + poisson(p.llmCallsMean - 1)
      sum.llmCalls += n
      sum.toolCalls += (n - 1) * p.toolCallsPerStep
      for (let i = 0; i < n; i++) sum.promptTokens += p.basePromptTokens + i * p.contextGrowthTokensPerStep
      sum.outputTokens += n * p.outputTokensPerCall
    }
    const expected = agentPerRequest(p)
    for (const k of Object.keys(sum) as (keyof typeof sum)[]) expect(sum[k] / N / expected[k]).toBeCloseTo(1, 2)
  })
})
