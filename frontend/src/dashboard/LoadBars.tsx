import { count, level, LEVEL_ICON, pct } from '../lib/format'
import type { RunResult } from '../types/contracts'

// Average utilization per node, busiest first, with a tick at its peak. The bar's color, icon and
// text all say the load level, so hue is never the only signal. Kinds without a capacity limit are left out.
const UNBOUNDED = new Set(['users', 'loadBalancer', 'cache', 'agent'])

export default function LoadBars({ result, label }: { result: RunResult; label: (id: string) => string }) {
  const rows = result.nodes.filter((n) => !UNBOUNDED.has(n.kind)).sort((a, b) => b.utilAvg - a.utilAvg)
  if (!rows.length) return <p className="text-sm text-muted">No nodes with capacity to measure.</p>
  const top = rows[0]
  return (
    <figure className="flex flex-col gap-3">
      <figcaption className="text-sm">
        Busiest: {label(top.id)} at {pct(top.utilAvg)} on average, peaking at {pct(top.utilMax)}.
      </figcaption>
      <ul className="grid grid-cols-[minmax(6rem,10rem)_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 text-sm">
        {rows.map((n) => {
          const lv = level(n.utilAvg)
          return (
            <li key={n.id} className="contents">
              <span className="truncate">{label(n.id)}</span>
              <span className="relative h-2 rounded bg-panel-2" aria-hidden>
                <span className="absolute inset-y-0 left-0 rounded" style={{ width: pct(Math.min(1, n.utilAvg)), background: `var(--${lv})` }} />
                <span className="absolute -inset-y-1 w-0.5 bg-text" style={{ left: pct(Math.min(1, n.utilMax)) }} title="peak" />
              </span>
              <span className="num text-xs">
                <span style={{ color: `var(--${lv})` }} aria-hidden>{LEVEL_ICON[lv]}</span>{' '}
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
