import { count, pct } from '../lib/format'
import type { GpuPoint, RunResult } from '../api/api'
import LineChart from './LineChart'

// Self-hosted LLM replicas: KV-cache use and the batch, one snapshot per simulated second. Two charts per
// node on the same time axis, since a share and a count don't belong on one y-axis: under a spike the KV
// line reaches the top and, from then on, the waiting line climbs.
export default function GpuChart({ result, label, markAt }: { result: RunResult; label: (id: string) => string; markAt?: number }) {
  if (!result.gpu.length) return <p className="text-[13px] text-muted">No self-hosted LLMs in this design, so there is no GPU to show.</p>
  return (
    <div className="flex flex-col gap-6">
      {result.gpu.map(({ nodeId, points }) => {
        const xs = points.map((p) => p.t)
        const full = points.filter((p) => p.kvPct >= 0.95).length / points.length
        const kv = peak(points, 'kvPct')
        const waiting = peak(points, 'waiting')
        const waitingNote = waiting.waiting
          ? `the waiting line peaks at ${count(waiting.waiting)} at ${waiting.t} s`
          : 'nothing ever waits for a place in it'
        return (
          <section key={nodeId} className="flex flex-col gap-3">
            <h3 className="text-[13px] font-semibold">{label(nodeId)}</h3>
            <LineChart
              xs={xs}
              max={1}
              format={(v) => pct(v)}
              markAt={markAt}
              summary={`KV cache use peaks at ${pct(kv.kvPct)} at ${kv.t} s and is full ${pct(full)} of the time.`}
              series={[{ label: 'KV cache', color: 'var(--series-1)', values: points.map((p) => p.kvPct) }]}
            />
            <LineChart
              xs={xs}
              format={(v) => count(v)}
              markAt={markAt}
              summary={`Up to ${count(peak(points, 'batch').batch)} sequences run in a batch; ${waitingNote}.`}
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

/** The first point where `key` is highest. */
const peak = (points: GpuPoint[], key: 'kvPct' | 'batch' | 'waiting') => points.reduce((a, b) => (b[key] > a[key] ? b : a))
