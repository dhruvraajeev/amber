import { count, pct } from '../lib/format'
import type { RunResult } from '../types/contracts'
import LineChart from './LineChart'

// Self-hosted LLM replicas: KV-cache use and the batch. Two charts per node, since a share and a
// count don't belong on one axis.
export default function GpuChart({ result, label }: { result: RunResult; label: (id: string) => string }) {
  if (!result.gpu.length) return <p className="text-sm text-muted">No self-hosted LLMs in this design, so there is no GPU to show.</p>
  return (
    <div className="flex flex-col gap-6">
      {result.gpu.map(({ nodeId, points }) => {
        const xs = points.map((p) => p.t)
        const full = points.filter((p) => p.kvPct >= 0.95).length / points.length
        const peakKv = Math.max(...points.map((p) => p.kvPct))
        const peakBatch = Math.max(...points.map((p) => p.batch))
        const peakWaiting = Math.max(...points.map((p) => p.waiting))
        return (
          <section key={nodeId} className="flex flex-col gap-3">
            <h3 className="text-sm font-semibold">{label(nodeId)}</h3>
            <LineChart
              xs={xs}
              max={1}
              format={(v) => pct(v)}
              summary={`KV cache peaks at ${pct(peakKv)} of GPU memory and is full ${pct(full)} of the time.`}
              series={[{ label: 'KV cache', color: 'var(--series-1)', values: points.map((p) => p.kvPct) }]}
            />
            <LineChart
              xs={xs}
              format={(v) => count(v)}
              summary={`Up to ${count(peakBatch)} sequences run in a batch, with up to ${count(peakWaiting)} waiting.`}
              series={[
                { label: 'running', color: 'var(--series-1)', values: points.map((p) => p.batch) },
                { label: 'waiting', color: 'var(--series-3)', values: points.map((p) => p.waiting) },
              ]}
            />
          </section>
        )
      })}
    </div>
  )
}
