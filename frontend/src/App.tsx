import { useState } from 'react'
import Canvas from './canvas/Canvas'
import { BLANK } from './canvas/map'
import EmptyState from './layout/EmptyState'
import TopBar from './layout/TopBar'
import type { Design } from './types/contracts'

const templates = Object.values(
  import.meta.glob<Design>('@shared/templates/*.json', { eager: true, import: 'default' }),
)

// The editor page: layout regions per §11.2. The store (Step 6) will own `design`.
export default function App() {
  // `key` changes on every load so the canvas remounts with fresh nodes.
  const [loaded, setLoaded] = useState<{ design: Design; key: number } | null>(null)
  const load = (d: Design) => setLoaded({ design: structuredClone(d), key: Date.now() })

  return (
    <div className="grid h-full grid-rows-[auto_minmax(0,1fr)_auto_auto]">
      <TopBar>
        {loaded && <span className="truncate">{loaded.design.name}</span>}
        <select
          aria-label="Load a template"
          value=""
          onChange={(e) => load(e.target.value === 'blank' ? BLANK : templates[Number(e.target.value)])}
          className="rounded border border-border bg-panel-2 px-2 py-1 text-sm"
        >
          <option value="" disabled>
            Templates
          </option>
          {templates.map((t, i) => (
            <option key={t.name} value={i}>
              {t.name}
            </option>
          ))}
          <option value="blank">Blank canvas</option>
        </select>
      </TopBar>

      <div className="grid min-h-0 grid-cols-[10rem_minmax(0,1fr)_18rem]">
        {loaded ? (
          <Canvas key={loaded.key} design={loaded.design} />
        ) : (
          <>
            <main className="col-span-2 min-h-0 bg-bg">
              <EmptyState templates={templates} onPick={load} />
            </main>
            <aside className="border-l border-border bg-panel p-3 text-sm text-muted">
              Select a node to edit its parameters.
            </aside>
          </>
        )}
      </div>

      <footer className="border-t border-border bg-panel px-4 py-2 text-sm text-muted">
        Run controls appear here once a design is ready.
      </footer>
      <section className="h-32 border-t border-border bg-panel px-4 py-2 text-sm text-muted">
        Run a simulation to see results.
      </section>
    </div>
  )
}
