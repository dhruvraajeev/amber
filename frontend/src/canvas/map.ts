import type { Edge, Node } from '@xyflow/react'
import { Bot, BrainCircuit, Database, Server, Split, Users, Zap, type LucideIcon } from 'lucide-react'
import hostedLlms from '@shared/presets/hosted_llms.json'
import type { Design, DesignEdge, DesignNode, LlmParams, NodeKind, NodeParamsByKind } from '../api/api'

export const BLANK: Design = { name: 'Untitled design', version: 1, nodes: [], edges: [] }

// Translation between the §7 Design contract and React Flow's node/edge shapes.

// A DesignNode minus the fields React Flow already stores on its own node (id, position).
type Body<N> = N extends DesignNode ? Omit<N, 'id' | 'position'> : never
export type NodeData = Body<DesignNode>
export type FlowNode = Node<NodeData, NodeKind>
export type FlowEdge = Edge<{ role?: DesignEdge['role'] }>

// One way only: the store holds the Design, and the canvas renders it through this.
export const toFlowNode = ({ id, position, ...data }: DesignNode): FlowNode => ({ id, position, type: data.kind, data: data as NodeData })
export const toFlowEdge = ({ id, source, target, role }: DesignEdge): FlowEdge => ({ id, source, target, type: 'traffic', data: { role }, label: role })

// ── Palette entries and defaults for newly dropped nodes ────────────────────

export const KINDS: { kind: NodeKind; name: string; icon: LucideIcon }[] = [
  { kind: 'users', name: 'Users', icon: Users },
  { kind: 'loadBalancer', name: 'Load balancer', icon: Split },
  { kind: 'service', name: 'Service', icon: Server },
  { kind: 'cache', name: 'Cache', icon: Zap },
  { kind: 'database', name: 'Database', icon: Database },
  { kind: 'agent', name: 'Agent', icon: Bot },
  { kind: 'llm', name: 'LLM', icon: BrainCircuit },
]

const llmPreset = hostedLlms[0]
// The inspector swaps between these when the LLM mode changes.
export const LLM_DEFAULTS: { [M in LlmParams['mode']]: Extract<LlmParams, { mode: M }> } = {
  hosted: {
    mode: 'hosted', presetId: llmPreset.id, ttft: llmPreset.ttft, tokensPerSecond: llmPreset.tokensPerSecond,
    inputUsdPer1M: llmPreset.inputUsdPer1M, outputUsdPer1M: llmPreset.outputUsdPer1M,
    rateLimitRpm: llmPreset.rateLimitRpm, maxRetries: 2,
  },
  selfHosted: {
    mode: 'selfHosted', gpuPresetId: 'nvidia-l4-24gb', modelPresetId: 'llama-3.1-8b-instruct-fp16', profileId: 'default',
    replicas: 1, maxBatchSize: 32, maxBatchTokens: 4096, maxOutputTokensReserve: 512,
    speculative: { enabled: false, draftTokens: 4, acceptanceRate: 0.7, draftStepMs: 3 },
  },
}
const DEFAULTS: { [K in NodeKind]: NodeParamsByKind[K] } = {
  users: { traffic: { type: 'constant', rps: 50 }, clientTimeoutMs: 5000 },
  loadBalancer: { algorithm: 'roundRobin', overhead: { p50Ms: 1, p99Ms: 3 } },
  service: { replicas: 2, concurrencyPerReplica: 50, queueLimit: 200, work: { p50Ms: 20, p99Ms: 100 }, costPerReplicaMonth: 30 },
  cache: { hitRate: 0.8, latency: { p50Ms: 1, p99Ms: 4 }, costPerMonth: 25 },
  database: { preset: 'postgres', connectionPool: 50, queueLimit: 200, query: { p50Ms: 4, p99Ms: 25 }, costPerMonth: 60 },
  agent: {
    llmCallsMean: 3, toolCallsPerStep: 1, toolLatency: { p50Ms: 100, p99Ms: 500 },
    basePromptTokens: 1000, contextGrowthTokensPerStep: 300, outputTokensPerCall: 200,
  },
  llm: LLM_DEFAULTS.hosted,
}

export function newNode(kind: NodeKind, position: { x: number; y: number }, taken: Set<string>): DesignNode {
  let id: string
  do id = `n_${crypto.randomUUID().slice(0, 4)}`
  while (taken.has(id))
  const label = KINDS.find((k) => k.kind === kind)!.name
  return { id, kind, label, position, params: structuredClone(DEFAULTS[kind]) } as DesignNode
}

// ── Layout for designs that arrive without one ──────────────────────────────

// A design from an AI agent (via Amber's MCP link) or a hand-written file has no real positions: every
// node sits at 0,0. Lay those out left to right by call depth, so the canvas reads like the templates.
// A design whose nodes are already spread out is returned untouched.
export function withLayout(design: Design): Design {
  const spots = new Set(design.nodes.map((n) => (n.position ? `${n.position.x},${n.position.y}` : '')))
  if (design.nodes.length < 2 || (spots.size === design.nodes.length && !spots.has(''))) return design
  // Depth = the longest chain of edges leading to a node. Capped at one pass per node, so a (still
  // invalid) cycle ends instead of looping.
  const depth = new Map(design.nodes.map((n) => [n.id, 0]))
  for (let pass = 0; pass < design.nodes.length; pass++) {
    for (const e of design.edges) {
      const d = (depth.get(e.source) ?? 0) + 1
      if (depth.has(e.target) && d > depth.get(e.target)!) depth.set(e.target, d)
    }
  }
  const columns = new Map<number, number>() // depth → nodes placed in it so far
  const count = (d: number) => design.nodes.filter((n) => depth.get(n.id) === d).length
  const nodes = design.nodes.map((n) => {
    const d = depth.get(n.id)!
    const row = columns.get(d) ?? 0
    columns.set(d, row + 1)
    return { ...n, position: { x: d * 240, y: 150 + (row - (count(d) - 1) / 2) * 180 } }
  })
  return { ...design, nodes }
}
