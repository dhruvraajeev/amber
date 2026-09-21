import type { NodeKind } from '../types/contracts'
import { KINDS } from './map'

export const DRAG_MIME = 'application/amber-kind'

// Drag a kind onto the canvas, or click (or Enter) to drop it in the middle of the view.
export default function Palette({ onAdd }: { onAdd: (kind: NodeKind) => void }) {
  return (
    <aside className="flex flex-col gap-1 border-r border-border bg-panel p-2" aria-label="Node palette">
      {KINDS.map(({ kind, name, icon }) => (
        <button
          key={kind}
          draggable
          onDragStart={(e) => {
            e.dataTransfer.setData(DRAG_MIME, kind)
            e.dataTransfer.effectAllowed = 'move'
          }}
          onClick={() => onAdd(kind)}
          className="flex cursor-grab items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-panel-2"
        >
          <span className="w-4 text-accent" aria-hidden>
            {icon}
          </span>
          {name}
        </button>
      ))}
    </aside>
  )
}
