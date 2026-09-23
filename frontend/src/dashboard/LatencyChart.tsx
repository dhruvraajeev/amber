import { ms } from '../lib/format'
import type { RunResult } from '../types/contracts'
import LineChart from './LineChart'

// Latency percentiles over the run. Series colors are §11.3's ramp, picked for contrast between neighbours.
export default function LatencyChart({ result }: { result: RunResult }) {
  const tl = result.timeline
  const worst = tl.reduce((a, b) => (b.p99 > a.p99 ? b : a), tl[0])
  const { p50, p99 } = result.summary.latencyMs
  return (
    <LineChart
      xs={tl.map((p) => p.t)}
      format={ms}
      summary={`Half of requests finish within ${ms(p50)} and 99% within ${ms(p99)}; p99 is worst at ${worst.t} s (${ms(worst.p99)}).`}
      series={[
        { label: 'p50', color: 'var(--series-4)', values: tl.map((p) => p.p50) },
        { label: 'p95', color: 'var(--series-1)', values: tl.map((p) => p.p95) },
        { label: 'p99', color: 'var(--series-3)', values: tl.map((p) => p.p99) },
      ]}
    />
  )
}
