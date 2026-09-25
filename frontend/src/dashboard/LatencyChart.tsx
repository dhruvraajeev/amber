import { ms } from '../lib/format'
import type { RunResult } from '../api/api'
import LineChart from './LineChart'

// Latency percentiles over the run, from calm to hot: p50 warm white, p95 orange, p99 red. Runs with an
// LLM also get time to first token: how long before a streamed answer starts to appear.
export default function LatencyChart({ result, markAt }: { result: RunResult; markAt?: number }) {
  const tl = result.timeline
  const worst = tl.reduce((a, b) => (b.p99 > a.p99 ? b : a), tl[0])
  const { p50, p99 } = result.summary.latencyMs
  const ttft = result.summary.ttftMs
  return (
    <div className="flex flex-col gap-4">
      <LineChart
        xs={tl.map((p) => p.t)}
        format={ms}
        markAt={markAt}
        summary={`Half of requests finish within ${ms(p50)} and 99% within ${ms(p99)}; p99 is worst at ${worst.t} s (${ms(worst.p99)}).`}
        series={[
          { label: 'p50', color: 'var(--series-2)', values: tl.map((p) => p.p50) },
          { label: 'p95', color: 'var(--series-1)', values: tl.map((p) => p.p95) },
          { label: 'p99', color: 'var(--series-3)', values: tl.map((p) => p.p99) },
        ]}
      />
      {ttft && (
        <section className="flex flex-col gap-2 border-t border-border pt-3" aria-label="Time to first token">
          <p className="text-[13px]">
            Time to first token <span className="text-muted">· the wait before an answer starts to stream, queueing included</span>
          </p>
          <dl className="flex gap-8">
            {(['p50', 'p95', 'p99'] as const).map((k) => (
              <div key={k}>
                <dt className="num text-[11px] text-muted">{k}</dt>
                <dd className="figure text-[17px] font-semibold">{ms(ttft[k])}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}
    </div>
  )
}
