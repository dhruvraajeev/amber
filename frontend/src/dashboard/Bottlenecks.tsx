import { ChevronRight, CircleAlert, Info, TriangleAlert } from 'lucide-react'
import type { RunResult } from '../api/api'

const ICON = { critical: CircleAlert, warn: TriangleAlert, info: Info } as const
const COLOR = { critical: 'text-crit', warn: 'text-warn', info: 'text-muted' } as const
const EDGE = { critical: 'border-crit/40 bg-crit/[0.06]', warn: 'border-warn/30 bg-warn/[0.05]', info: 'border-border bg-panel-2' } as const

// Plain-English findings, worst first (§8.9). Clicking one selects its node on the canvas.
export default function Bottlenecks({ result, onSelect }: { result: RunResult; onSelect: (id: string) => void }) {
  const found = result.bottlenecks
  const serious = found.filter((b) => b.severity !== 'info').length
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[13px]">{serious ? `${serious} problem${serious > 1 ? 's' : ''} found.` : 'Nothing is overloaded.'}</p>
      <ul className="flex flex-col gap-2 text-[13px]">
        {found.map((b, i) => {
          const Icon = ICON[b.severity]
          return (
            <li key={i}>
              <button
                disabled={!b.nodeId}
                onClick={() => b.nodeId && onSelect(b.nodeId)}
                className={`group flex w-full items-start gap-3 rounded-xl border px-3.5 py-2.5 text-left transition-colors enabled:hover:border-accent/60 ${EDGE[b.severity]}`}
              >
                <Icon size={16} className={`mt-0.5 shrink-0 ${COLOR[b.severity]}`} aria-hidden />
                <span className="flex-1 leading-snug">
                  <span className="sr-only">{b.severity}: </span>
                  {b.message}
                </span>
                {b.nodeId && <ChevronRight size={15} className="mt-0.5 shrink-0 text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-accent" aria-hidden />}
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
