import gpus from '@shared/presets/gpus.json'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { hasCapacity, loadColor, loadGlow } from '../../lib/color'
import { level, pct, rps } from '../../lib/format'
import { useNodeLoad } from '../../run/Playback'
import { useStore } from '../../store'
import LevelIcon from '../../ui/LevelIcon'
import { KINDS, type FlowNode, type NodeData } from '../map'

// One card for all seven kinds (§11.3): icon + label + one key line. Before a run the key line
// summarizes params; after, it shows load at the playhead, and the border and glow follow utilization.
// A node named by a warning or critical bottleneck gets a pulsing "!" badge.
export default function NodeCard({ id, data, selected }: NodeProps<FlowNode>) {
  const { icon: Icon } = KINDS.find((k) => k.kind === data.kind)!
  const load = useNodeLoad(id)
  const bottleneck = useStore((s) => s.result?.bottlenecks.some((b) => b.nodeId === id && b.severity !== 'info'))
  const glows = load && hasCapacity(data.kind) && !selected // the selection glow wins over the load glow
  return (
    <div
      className={`relative min-w-44 rounded-xl border bg-[linear-gradient(180deg,rgb(255_255_255/0.05),rgb(255_255_255/0)_60%),var(--panel-2)] py-2.5 pr-3.5 pl-2.5 shadow-[0_10px_24px_-12px_rgb(0_0_0/0.9)] transition-[border-color,box-shadow] duration-200 ${
        selected ? 'border-accent shadow-[0_0_0_3px_rgb(255_106_43/0.2),0_10px_30px_-8px_rgb(255_106_43/0.5)]' : 'border-border-strong'
      }`}
      style={glows ? { borderColor: loadColor(load.util), boxShadow: `${loadGlow(load.util)}, 0 10px 24px -12px rgb(0 0 0 / 0.9)` } : undefined}
    >
      {data.kind !== 'users' && <Handle type="target" position={Position.Left} />}
      {bottleneck && (
        <span
          title="Bottleneck: see the Bottlenecks tab"
          className="absolute -top-2 -left-2 grid size-[18px] place-items-center rounded-full bg-crit text-[10px] font-bold text-text shadow-[0_0_12px_rgb(240_67_58/0.7)] motion-safe:animate-pulse"
        >
          !
        </span>
      )}
      <div className="flex items-center gap-2.5">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg border border-accent/20 bg-accent/10 text-accent">
          <Icon size={16} strokeWidth={1.75} aria-hidden />
        </span>
        <div className="min-w-0">
          <div className="truncate text-[13px] font-medium leading-tight">{data.label}</div>
          <div className="num mt-0.5 flex items-center gap-1 text-[11px] leading-tight text-muted">
            {load ? <LoadLine util={hasCapacity(data.kind) ? load.util : undefined} throughput={load.throughputRps} /> : keyLine(data)}
          </div>
        </div>
      </div>
      {data.kind !== 'database' && data.kind !== 'llm' && <Handle type="source" position={Position.Right} />}
    </div>
  )
}

/** "▲ 72% · 140 req/s": the icon repeats the load level, so it isn't carried by color alone. */
function LoadLine({ util, throughput }: { util?: number; throughput: number }) {
  if (util === undefined) return rps(throughput)
  return (
    <>
      <LevelIcon level={level(util)} size={11} />
      <span className="text-text">{pct(util)}</span> · {rps(throughput)}
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
    case 'llm': {
      const p = d.params
      if (p.mode === 'hosted') return p.presetId
      return `${p.replicas} × ${gpus.find((g) => g.id === p.gpuPresetId)?.name ?? p.gpuPresetId}`
    }
  }
}
