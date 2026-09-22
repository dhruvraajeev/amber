import { Handle, Position, type NodeProps } from '@xyflow/react'
import { KINDS, type FlowNode, type NodeData } from '../map'

// One card for all seven kinds (§11.3): icon + label + one key line.
// Before a run the key line summarizes params; Step 8 swaps in live metrics and load glow.
export default function NodeCard({ data, selected }: NodeProps<FlowNode>) {
  const { icon } = KINDS.find((k) => k.kind === data.kind)!
  return (
    <div
      className={`min-w-36 rounded-md border bg-panel px-3 py-2 ${selected ? 'border-accent ring-2 ring-accent/40' : 'border-border'}`}
    >
      {data.kind !== 'users' && <Handle type="target" position={Position.Left} />}
      <div className="flex items-center gap-2">
        <span className="text-accent" aria-hidden>
          {icon}
        </span>
        <span className="text-sm font-semibold">{data.label}</span>
      </div>
      <div className="num mt-1 text-xs text-muted">{keyLine(data)}</div>
      {data.kind !== 'database' && data.kind !== 'llm' && <Handle type="source" position={Position.Right} />}
    </div>
  )
}

function keyLine(d: NodeData): string {
  switch (d.kind) {
    case 'users': {
      const t = d.params.traffic
      if (t.type === 'constant') return `${t.rps} rps`
      if (t.type === 'spike') return `${t.baseRps}→${t.peakRps} rps spike`
      return `${t.startRps}→${t.endRps} rps ramp`
    }
    case 'loadBalancer':
      return d.params.algorithm === 'roundRobin' ? 'round robin' : 'least connections'
    case 'service':
      return `${d.params.replicas} × ${d.params.concurrencyPerReplica} · ${d.params.work.p50Ms} ms p50`
    case 'cache':
      return `${Math.round(d.params.hitRate * 100)}% hit · $${d.params.costPerMonth}/mo`
    case 'database':
      return `${d.params.preset} · pool ${d.params.connectionPool}`
    case 'agent':
      return `~${d.params.llmCallsMean} LLM calls`
    case 'llm':
      return d.params.mode === 'hosted' ? d.params.presetId : `${d.params.replicas} × ${d.params.gpuPresetId}`
  }
}
