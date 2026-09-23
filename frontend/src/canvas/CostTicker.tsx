import { useEffect, useRef, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { usd } from '../lib/format'
import { useStore } from '../store'
import type { Design, RunResult } from '../types/contracts'

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
      className="pointer-events-none absolute top-3 right-3 z-10 rounded-md border border-border bg-panel/90 px-3 py-2 text-right"
    >
      <div className="num text-lg">{usd(total)}/mo</div>
      <div className="num text-xs text-muted">{usd(now)}/mo at {point?.t ?? 0} s</div>
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

/** Eases from the last shown value to `target` over 800 ms (ease-out cubic). Jumps under reduced motion. */
function useCountUp(target: number): number {
  const [value, setValue] = useState(0)
  const shown = useRef(0)
  useEffect(() => {
    const from = shown.current
    const set = (v: number) => setValue((shown.current = v))
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return set(target)
    const t0 = performance.now()
    let raf = 0
    const frame = (now: number) => {
      const k = Math.min(1, (now - t0) / 800)
      set(from + (target - from) * (1 - (1 - k) ** 3))
      if (k < 1) raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [target])
  return value
}
