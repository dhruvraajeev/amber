import { useShallow } from 'zustand/react/shallow'
import { usd } from '../lib/format'
import { useCountUp } from '../lib/useCountUp'
import { useStore } from '../store'
import type { Design, RunResult } from '../api/api'

// The cost ticker on the canvas (§11.3): counts up to the run's monthly total when it arrives, and shows
// what the month would cost if traffic stayed as it is at the playhead.
export default function CostTicker() {
  const { result, playhead, design } = useStore(useShallow((s) => ({ result: s.result, playhead: s.playhead, design: s.design })))
  const total = useCountUp(result?.cost.monthlyTotalUsd ?? 0)
  if (!result || !design) return null
  const point = result.timeline[playhead]
  const now = costAt(result, design, playhead)
  return (
    <div
      role="img"
      aria-label={`Estimated ${usd(result.cost.monthlyTotalUsd)} a month; ${usd(now)} a month at the current traffic`}
      className="pointer-events-none absolute top-4 right-4 z-10 min-w-44 rounded-2xl border border-border bg-panel/85 px-4 py-3 shadow-[0_18px_40px_-20px_rgb(0_0_0/0.9),0_0_40px_-18px_rgb(255_106_43/0.6)] backdrop-blur-sm"
    >
      <div className="text-xs text-muted">Monthly cost</div>
      <div className="figure mt-0.5 text-[22px] font-semibold leading-tight">
        {usd(total)}
        <span className="text-sm font-normal text-muted">/mo</span>
      </div>
      <div className="num mt-1 text-[11px] text-muted">
        <span className="text-accent-2">{usd(now)}</span>/mo at {point?.t ?? 0} s
      </div>
    </div>
  )
}

/** Monthly cost if the playhead's traffic lasted all month. Only hosted LLMs bill per use (§8.10), so
 *  only they scale with the moment's throughput relative to the run's average; the rest is flat. */
function costAt(result: RunResult, design: Design, i: number): number {
  return result.cost.breakdown.reduce((sum, row) => {
    const node = design.nodes.find((n) => n.id === row.nodeId)
    if (node?.kind !== 'llm' || node.params.mode !== 'hosted') return sum + row.usd
    const rate = (p: RunResult['timeline'][number]) => p.nodes[row.nodeId]?.throughputRps ?? 0
    const avg = result.timeline.reduce((s, p) => s + rate(p), 0) / result.timeline.length
    return sum + (avg ? (row.usd * rate(result.timeline[i])) / avg : row.usd)
  }, 0)
}
