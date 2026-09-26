// Arithmetic behind the AI inspectors' read-outs. Each formula mirrors the simulator's (plan §8.5, §8.7),
// so what a form says is what a run does.

import gpus from '@shared/presets/gpus.json'
import models from '@shared/presets/models.json'
import type { AgentParams } from '../api/api'

/** Self-hosted timing profiles, `default` plus the measured ones (shared/profiles; backend: presets.profiles). */
export const profiles = Object.values(
  import.meta.glob<{ id: string; name: string }>('@shared/profiles/*.json', { eager: true, import: 'default' }),
)

/** Share of GPU memory the server may use (§8.7's gpu_memory_utilization; backend: kv_capacity_bytes). */
export const GPU_MEMORY_UTILIZATION = 0.9

export interface KvBudget {
  gpuName: string
  usableGb: number // GPU memory the server may use
  weightsGb: number
  capacityBytes: number // left for the KV cache once the weights are loaded; ≤ 0 when the model doesn't fit
  bytesPerToken: number
}

/** The KV cache one replica has, or undefined for an unknown preset id (validation reports that). */
export function kvBudget(gpuId: string, modelId: string): KvBudget | undefined {
  const gpu = gpus.find((g) => g.id === gpuId)
  const model = models.find((m) => m.id === modelId)
  if (!gpu || !model) return undefined
  const usableGb = gpu.memoryGb * GPU_MEMORY_UTILIZATION
  return {
    gpuName: gpu.name,
    usableGb,
    weightsGb: model.weightsGb,
    capacityBytes: (usableGb - model.weightsGb) * 1e9,
    // A key and a value vector per KV head, in every layer.
    bytesPerToken: 2 * model.nLayers * model.nKvHeads * model.headDim * model.bytesPerElement,
  }
}

/** What one agent request does on average. The call count is 1 + Poisson(λ) with λ = llmCallsMean − 1,
 *  tool calls happen between LLM calls, and call i (0-based) sends basePrompt + i × growth tokens. */
export function agentPerRequest(p: AgentParams) {
  const λ = p.llmCallsMean - 1
  // Σ i over i < n is n(n − 1)/2, and for n = 1 + K with K ~ Poisson(λ), E[n(n − 1)] = E[K + K²] = 2λ + λ².
  return {
    llmCalls: p.llmCallsMean,
    toolCalls: λ * p.toolCallsPerStep,
    promptTokens: p.llmCallsMean * p.basePromptTokens + (p.contextGrowthTokensPerStep * (2 * λ + λ * λ)) / 2,
    outputTokens: p.llmCallsMean * p.outputTokensPerCall,
  }
}
