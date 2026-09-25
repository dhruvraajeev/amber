import type { AnimationEvent, CSSProperties } from 'react'
import type { NodeKind } from '../api/api'
import { KINDS } from './map'

export const DRAG_MIME = 'application/amber-kind'

// The palette rail: drag a kind onto the canvas, or click (or Enter) to drop it in the view.
// Each icon burns (theme.css .ember-icon), staggered so they don't flicker in step.
export default function Palette({ onAdd }: { onAdd: (kind: NodeKind) => void }) {
  return (
    <aside
      className="panel row-span-3 flex flex-col items-stretch gap-1 overflow-y-auto p-1.5"
      aria-label="Node palette"
      onAnimationIteration={rerollWisp}
    >
      {KINDS.map(({ kind, name, icon: Icon }, i) => (
        <button
          key={kind}
          draggable
          onDragStart={(e) => {
            e.dataTransfer.setData(DRAG_MIME, kind)
            e.dataTransfer.effectAllowed = 'move'
          }}
          onClick={() => onAdd(kind)}
          title={`Add ${name.toLowerCase()} (drag onto the canvas, or click)`}
          className="group flex cursor-grab flex-col items-center gap-1.5 rounded-xl px-1 pt-2.5 pb-2 text-muted transition-colors hover:bg-panel-2 hover:text-text active:cursor-grabbing"
        >
          <span
            style={{ '--d': `${-i * 0.37}s` } as CSSProperties}
            className="ember-icon grid size-9 place-items-center rounded-[0.7rem] border border-border bg-panel-2 text-accent transition-[border-color,box-shadow] group-hover:border-accent/40 group-hover:shadow-[0_4px_14px_-4px_rgb(255_106_43/0.55)]"
          >
            <Icon size={17} strokeWidth={1.75} aria-hidden />
          </span>
          <span className="text-center text-[10.5px] leading-tight">{name}</span>
        </button>
      ))}
    </aside>
  )
}

/** A wisp just faded out: give its next rise a new heading and lean, mostly upward, drifting either way. */
function rerollWisp(e: AnimationEvent) {
  const icon = e.target as HTMLElement
  if (!icon.classList.contains('ember-icon')) return // the glyph's flicker also bubbles here
  const w = e.nativeEvent.pseudoElement === '::after' ? 'b' : 'a'
  const between = (lo: number, hi: number) => lo + Math.random() * (hi - lo)
  icon.style.setProperty(`--${w}x`, `${between(-13, 13).toFixed(1)}px`)
  icon.style.setProperty(`--${w}y`, `${between(-34, -18).toFixed(1)}px`)
  icon.style.setProperty(`--${w}r`, `${between(-35, 35).toFixed(0)}deg`)
}
