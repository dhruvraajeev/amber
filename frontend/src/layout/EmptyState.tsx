import type { Design } from '../types/contracts'

// Empty state (§11.3): three template cards and "Blank canvas".
export default function EmptyState({ templates, onPick }: { templates: Design[]; onPick: (d: Design) => void }) {
  return (
    <div className="grid h-full place-items-center overflow-auto p-4">
      <div className="w-full max-w-2xl rounded-lg border border-border bg-panel p-6">
        <h1 className="text-lg font-semibold">Start from a template</h1>
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          {templates.map((t) => (
            <button
              key={t.name}
              onClick={() => onPick(t)}
              className="rounded-md border border-border bg-panel-2 p-4 text-left hover:border-accent"
            >
              <span className="font-semibold">{t.name}</span>
              <span className="num mt-1 block text-xs text-muted">
                {t.nodes.length} nodes · {t.edges.length} edges
              </span>
            </button>
          ))}
        </div>
        <button
          onClick={() => onPick({ name: 'Untitled design', version: 1, nodes: [], edges: [] })}
          className="mt-4 text-accent hover:text-accent-2"
        >
          Blank canvas
        </button>
      </div>
    </div>
  )
}
