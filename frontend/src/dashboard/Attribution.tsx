import { pct } from '../lib/format'
import type { RunResult } from '../types/contracts'

const QUEUE = 'var(--series-3)'
const WORK = 'var(--series-1)'

// Where the slowest requests (≥ p99) spend their time, split into waiting in a queue and doing work.
export default function Attribution({ result, label }: { result: RunResult; label: (id: string) => string }) {
  const rows = result.attribution
  if (!rows.length) return <p className="text-sm text-muted">No slow requests to break down.</p>
  const top = rows[0]
  const waiting = top.queueShare > top.workShare
  return (
    <figure className="flex flex-col gap-3">
      <figcaption className="text-sm">
        {pct(top.queueShare + top.workShare)} of slow-request time is spent in {label(top.nodeId)}, mostly{' '}
        {waiting ? 'waiting in its queue' : 'doing its own work'}.
      </figcaption>
      <ul className="flex gap-4 text-xs text-muted">
        <li className="flex items-center gap-1.5"><span className="h-2 w-3 rounded-sm" style={{ background: QUEUE }} />waiting</li>
        <li className="flex items-center gap-1.5"><span className="h-2 w-3 rounded-sm" style={{ background: WORK }} />working</li>
      </ul>
      <ul className="grid grid-cols-[minmax(6rem,10rem)_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 text-sm">
        {rows.map((r) => (
          <li key={r.nodeId} className="contents">
            <span className="truncate">{label(r.nodeId)}</span>
            <span className="flex h-2 gap-0.5" aria-hidden>
              {r.queueShare > 0 && <span className="rounded-sm" style={{ width: pct(r.queueShare, 1), background: QUEUE }} />}
              {r.workShare > 0 && <span className="rounded-sm" style={{ width: pct(r.workShare, 1), background: WORK }} />}
            </span>
            <span className="num text-xs">
              {pct(r.queueShare + r.workShare)} <span className="text-muted">({pct(r.queueShare)} waiting · {pct(r.workShare)} working)</span>
            </span>
          </li>
        ))}
      </ul>
    </figure>
  )
}
