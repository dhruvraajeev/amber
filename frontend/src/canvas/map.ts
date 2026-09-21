import type { Edge, Node } from '@xyflow/react'
import hostedLlms from '@shared/presets/hosted_llms.json'
import type { Design, DesignEdge, DesignNode, NodeKind, NodeParamsByKind } from '../types/contracts'

// Translation between the §7 Design contract and React Flow's node/edge shapes,
// plus the canonical form used for `designHash`.

// A DesignNode minus the fields React Flow already stores on its own node (id, position).
type Body<N> = N extends DesignNode ? Omit<N, 'id' | 'position'> : never
export type NodeData = Body<DesignNode>
export type FlowNode = Node<NodeData, NodeKind>
export type FlowEdge = Edge<{ role?: DesignEdge['role'] }>

export function toFlow(design: Design): { nodes: FlowNode[]; edges: FlowEdge[] } {
  return {
    nodes: design.nodes.map(({ id, position, ...data }) => ({ id, position, type: data.kind, data: data as NodeData })),
    edges: design.edges.map(({ id, source, target, role }) => ({ id, source, target, data: { role }, label: role })),
  }
}

// `base` supplies the non-graph fields (name, version, id).
export function toDesign(base: Design, nodes: FlowNode[], edges: FlowEdge[]): Design {
  return {
    ...base,
    nodes: nodes.map((n) => ({ id: n.id, position: { x: n.position.x, y: n.position.y }, ...n.data }) as DesignNode),
    edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target, ...(e.data?.role && { role: e.data.role }) })),
  }
}

// Canonical JSON (§7.4): sorted keys, no positions, no undefined fields. Moving a node never changes it.
// The backend must produce byte-identical output (see docs/decisions.md).
export function canonicalDesign(design: Design): string {
  return stableStringify({ ...design, nodes: design.nodes.map((n) => ({ ...n, position: undefined })) })
}

function stableStringify(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(stableStringify).join(',')}]`
  if (v !== null && typeof v === 'object') {
    const o = v as Record<string, unknown>
    const keys = Object.keys(o).filter((k) => o[k] !== undefined).sort()
    return `{${keys.map((k) => `${JSON.stringify(k)}:${stableStringify(o[k])}`).join(',')}}`
  }
  return JSON.stringify(v)
}

export async function designHash(design: Design): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonicalDesign(design)))
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

// ── Palette entries and defaults for newly dropped nodes ────────────────────

export const KINDS: { kind: NodeKind; name: string; icon: string }[] = [
  { kind: 'users', name: 'Users', icon: '◎' },
  { kind: 'loadBalancer', name: 'Load balancer', icon: '⑂' },
  { kind: 'service', name: 'Service', icon: '▣' },
  { kind: 'cache', name: 'Cache', icon: '↯' },
  { kind: 'database', name: 'Database', icon: '≣' },
  { kind: 'agent', name: 'Agent', icon: '✳' },
  { kind: 'llm', name: 'LLM', icon: '✦' },
]

const llmPreset = hostedLlms[0]
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
  llm: {
    mode: 'hosted', presetId: llmPreset.id, ttft: llmPreset.ttft, tokensPerSecond: llmPreset.tokensPerSecond,
    inputUsdPer1M: llmPreset.inputUsdPer1M, outputUsdPer1M: llmPreset.outputUsdPer1M,
    rateLimitRpm: llmPreset.rateLimitRpm, maxRetries: 2,
  },
}

export function newNode(kind: NodeKind, position: { x: number; y: number }, taken: Set<string>): FlowNode {
  let id: string
  do id = `n_${crypto.randomUUID().slice(0, 4)}`
  while (taken.has(id))
  const name = KINDS.find((k) => k.kind === kind)!.name
  const data = { kind, label: name, params: structuredClone(DEFAULTS[kind]) } as NodeData
  return { id, position, type: kind, data }
}
