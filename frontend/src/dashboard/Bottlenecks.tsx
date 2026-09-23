import type { RunResult } from '../types/contracts'

const ICON = { critical: '✕', warn: '▲', info: 'ℹ' } as const
const COLOR = { critical: 'text-crit', warn: 'text-warn', info: 'text-muted' } as const

// Plain-English findings, worst first (§8.9). Clicking one selects its node on the canvas.
export default function Bottlenecks({ result, onSelect }: { result: RunResult; onSelect: (id: string) => void }) {
  const found = result.bottlenecks
  const serious = found.filter((b) => b.severity !== 'info').length
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm">{serious ? `${serious} problem${serious > 1 ? 's' : ''} found.` : 'Nothing is overloaded.'}</p>
      <ul className="flex flex-col gap-2 text-sm">
        {found.map((b, i) => (
          <li key={i}>
            <button
              disabled={!b.nodeId}
              onClick={() => b.nodeId && onSelect(b.nodeId)}
              className="flex w-full gap-2 rounded border border-border bg-panel-2 px-2 py-1.5 text-left enabled:hover:border-accent"
            >
              <span className={COLOR[b.severity]} aria-hidden>{ICON[b.severity]}</span>
              <span>
                <span className="sr-only">{b.severity}: </span>
                {b.message}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
