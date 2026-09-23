import { pct, usd } from '../lib/format'
import type { RunResult } from '../types/contracts'

// Estimated monthly cost, biggest line first, with the assumptions behind it (§8.10).
export default function CostCard({ result, label }: { result: RunResult; label: (id: string) => string }) {
  const { monthlyTotalUsd: total, breakdown, assumptions } = result.cost
  const rows = [...breakdown].sort((a, b) => b.usd - a.usd)
  return (
    <figure className="flex flex-col gap-3">
      <figcaption className="text-sm">
        About <span className="num">{usd(total)}</span> a month
        {rows.length > 0 && total > 0 && `, ${pct(rows[0].usd / total)} of it from ${label(rows[0].nodeId)}`}.
      </figcaption>
      <ul className="grid grid-cols-[minmax(6rem,10rem)_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 text-sm">
        {rows.map((r) => (
          <li key={r.nodeId} className="contents">
            <span className="truncate" title={r.detail}>{label(r.nodeId)}</span>
            <span className="h-2 rounded bg-panel-2" aria-hidden>
              <span className="block h-full rounded bg-accent" style={{ width: pct(total ? r.usd / total : 0) }} />
            </span>
            <span className="num text-right">
              {usd(r.usd)}/mo <span className="text-xs text-muted">{r.detail}</span>
            </span>
          </li>
        ))}
      </ul>
      <ul className="list-disc pl-4 text-xs text-muted">
        {assumptions.map((a) => <li key={a}>{a}</li>)}
      </ul>
    </figure>
  )
}
