import { hasCapacity } from '../lib/color'
import { count, level, pct } from '../lib/format'
import LevelIcon from '../ui/LevelIcon'
import type { RunResult } from '../types/contracts'

// Average utilization per node, busiest first, with a tick at its peak. The bar's color, icon and
// text all say the load level, so hue is never the only signal. Kinds without a capacity limit are left out.

export default function LoadBars({ result, label }: { result: RunResult; label: (id: string) => string }) {
  const rows = result.nodes.filter((n) => hasCapacity(n.kind)).sort((a, b) => b.utilAvg - a.utilAvg)
  if (!rows.length) return <p className="text-[13px] text-muted">No nodes with capacity to measure.</p>
  const top = rows[0]
  return (
    <figure className="flex flex-col gap-3">
      <figcaption className="text-[13px]">
        Busiest: {label(top.id)} at {pct(top.utilAvg)} on average, peaking at {pct(top.utilMax)}.
      </figcaption>
      <ul className="grid grid-cols-[minmax(6rem,10rem)_minmax(0,1fr)_auto] items-center gap-x-4 gap-y-3 text-[13px]">
        {rows.map((n) => {
          const lv = level(n.utilAvg)
          return (
            <li key={n.id} className="contents">
              <span className="truncate">{label(n.id)}</span>
              <span className="relative h-2 rounded-full bg-panel-3" aria-hidden>
                <span
                  className="absolute inset-y-0 left-0 rounded-full"
                  style={{ width: pct(Math.min(1, n.utilAvg)), background: `linear-gradient(90deg, color-mix(in srgb, var(--${lv}) 35%, transparent), var(--${lv}))`, boxShadow: `0 0 12px -2px var(--${lv})` }}
                />
                <span className="absolute -inset-y-1 w-0.5 rounded-full bg-text" style={{ left: pct(Math.min(1, n.utilMax)) }} title="peak" />
              </span>
              <span className="num flex items-center gap-1.5 text-xs">
                <LevelIcon level={lv} />
                {pct(n.utilAvg)} avg · {pct(n.utilMax)} peak
                <span className="text-muted">
                  {n.queueMax >= 1 && ` · queue ≤ ${count(n.queueMax)}`}
                  {n.rejects > 0 && ` · ${count(n.rejects)} rejected`}
                </span>
              </span>
            </li>
          )
        })}
      </ul>
    </figure>
  )
}
