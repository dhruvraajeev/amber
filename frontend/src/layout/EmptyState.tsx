import { ArrowUpRight, Plus } from 'lucide-react'
import { BLANK, KINDS } from '../canvas/map'
import type { Design } from '../types/contracts'

// Empty state (§11.3): three template cards and "Blank canvas", under an ember orb.
// Each card draws its template's real graph, so you can see the shape before you pick it.
export default function EmptyState({ templates, onPick }: { templates: Design[]; onPick: (d: Design) => void }) {
  return (
    <div className="panel grid h-full place-items-center overflow-auto px-6 py-10">
      <div className="flex w-full max-w-4xl flex-col items-center">
        <div className="orb size-40 sm:size-48" aria-hidden />
        <h1 className="mt-10 text-center text-3xl font-semibold tracking-[-0.03em] text-balance">Start from a template</h1>
        <p className="mt-2 text-center text-muted">Pick a starting architecture, then press Run to see where it breaks.</p>
        <div className="mt-10 grid w-full gap-4 sm:grid-cols-3">
          {templates.map((t) => (
            <button
              key={t.name}
              onClick={() => onPick(t)}
              className="spotlight group flex flex-col overflow-hidden rounded-2xl border border-border bg-panel-2 text-left transition-[border-color,box-shadow,translate] duration-200 hover:-translate-y-0.5 hover:border-accent/50 hover:shadow-[0_20px_40px_-20px_rgb(255_106_43/0.5)]"
            >
              <Preview design={t} />
              <span className="flex items-start justify-between gap-3 border-t border-border px-4 py-3.5">
                <span>
                  <span className="block font-medium">{t.name}</span>
                  <span className="num mt-1 block text-xs text-muted">
                    {t.nodes.length} nodes · {t.edges.length} edges
                  </span>
                </span>
                <ArrowUpRight size={16} className="mt-0.5 shrink-0 text-muted transition-colors group-hover:text-accent" aria-hidden />
              </span>
            </button>
          ))}
        </div>
        <button
          onClick={() => onPick(BLANK)}
          className="field mt-6 flex h-10 items-center gap-2 rounded-full px-4 text-[13px] text-muted hover:text-text"
        >
          <Plus size={15} aria-hidden />
          Blank canvas
        </button>
      </div>
    </div>
  )
}

/** The template's graph, fitted into a small frame: edges as faint curves, nodes as lit chips with their kind's icon. */
function Preview({ design }: { design: Design }) {
  const W = 300
  const H = 120
  const PAD = 26
  const xs = design.nodes.map((n) => n.position.x)
  const ys = design.nodes.map((n) => n.position.y)
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  const sx = (x: number) => PAD + (x1 > x0 ? ((x - x0) / (x1 - x0)) * (W - 2 * PAD) : (W - 2 * PAD) / 2)
  const sy = (y: number) => PAD + (y1 > y0 ? ((y - y0) / (y1 - y0)) * (H - 2 * PAD) : (H - 2 * PAD) / 2)
  const at = new Map(design.nodes.map((n) => [n.id, { x: sx(n.position.x), y: sy(n.position.y) }]))
  return (
    <span className="relative block h-32 bg-[radial-gradient(circle_at_50%_120%,rgb(255_106_43/0.14),transparent_65%)]" aria-hidden>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
        {design.edges.map((e) => {
          const [a, b] = [at.get(e.source), at.get(e.target)]
          if (!a || !b) return null
          const mx = (a.x + b.x) / 2
          return <path key={e.id} d={`M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}`} fill="none" stroke="rgb(255 255 255 / 0.18)" strokeWidth={1.25} vectorEffect="non-scaling-stroke" />
        })}
      </svg>
      {design.nodes.map((n) => {
        const p = at.get(n.id)!
        const Icon = KINDS.find((k) => k.kind === n.kind)!.icon
        return (
          <span
            key={n.id}
            className="absolute grid size-6 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-md border border-accent/30 bg-panel-3 text-accent shadow-[0_0_14px_-4px_rgb(255_106_43/0.8)]"
            style={{ left: `${(p.x / W) * 100}%`, top: `${(p.y / H) * 100}%` }}
          >
            <Icon size={12} strokeWidth={2} />
          </span>
        )
      })}
    </span>
  )
}
