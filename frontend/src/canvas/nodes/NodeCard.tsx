import { Handle, Position, type NodeProps } from '@xyflow/react'
import { hasCapacity, loadColor, loadGlow } from '../../lib/color'
import { level, LEVEL_ICON, pct, rps } from '../../lib/format'
import { useNodeLoad } from '../../run/Playback'
import { useStore } from '../../store'
import { KINDS, type FlowNode, type NodeData } from '../map'

// One card for all seven kinds (§11.3): icon + label + one key line. Before a run the key line
// summarizes params; after, it shows load at the playhead, and the border and glow follow utilization.
// A node named by a warning or critical bottleneck gets a pulsing "!" badge.
export default function NodeCard({ id, data, selected }: NodeProps<FlowNode>) {
  const { icon } = KINDS.find((k) => k.kind === data.kind)!
  const load = useNodeLoad(id)
  const bottleneck = useStore((s) => s.result?.bottlenecks.some((b) => b.nodeId === id && b.severity !== 'info'))
  const glows = load && hasCapacity(data.kind) && !selected // the selection ring wins over the glow
  return (
    <div
      className={`relative min-w-36 rounded-md border bg-panel px-3 py-2 ${selected ? 'border-accent ring-2 ring-accent/40' : 'border-border'}`}
      style={glows ? { borderColor: loadColor(load.util), boxShadow: loadGlow(load.util) } : undefined}
    >
      {data.kind !== 'users' && <Handle type="target" position={Position.Left} />}
      {bottleneck && (
        <span
          title="Bottleneck: see the Bottlenecks tab"
          className="absolute -top-2 -left-2 grid size-4 place-items-center rounded-full bg-crit text-[10px] font-bold text-text motion-safe:animate-pulse"
        >
          !
        </span>
      )}
      <div className="flex items-center gap-2">
        <span className="text-accent" aria-hidden>
          {icon}
        </span>
        <span className="text-sm font-semibold">{data.label}</span>
      </div>
      <div className="num mt-1 text-xs text-muted">
        {load ? <LoadLine util={hasCapacity(data.kind) ? load.util : undefined} throughput={load.throughputRps} /> : keyLine(data)}
      </div>
      {data.kind !== 'database' && data.kind !== 'llm' && <Handle type="source" position={Position.Right} />}
    </div>
  )
}

/** "▲ 72% · 140 req/s": the icon repeats the load level, so it isn't carried by color alone. */
function LoadLine({ util, throughput }: { util?: number; throughput: number }) {
  if (util === undefined) return rps(throughput)
  const lv = level(util)
  return (
    <>
      <span style={{ color: `var(--${lv})` }} aria-hidden>{LEVEL_ICON[lv]}</span> {pct(util)} · {rps(throughput)}
    </>
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
