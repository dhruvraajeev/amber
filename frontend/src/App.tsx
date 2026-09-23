import { useEffect, useState } from 'react'
import { getTemplates } from './api/api'
import Canvas from './canvas/Canvas'
import Dashboard from './dashboard/Dashboard'
import { BLANK } from './canvas/map'
import EmptyState from './layout/EmptyState'
import TopBar from './layout/TopBar'
import RunBar from './run/RunBar'
import { useStore } from './store'
import type { Design } from './types/contracts'

// The editor page: layout regions per §11.2. The design itself lives in the store (and is autosaved),
// so a refresh reopens it instead of the empty state.
export default function App() {
  const [templates, setTemplates] = useState<Design[]>([])
  useEffect(() => void getTemplates().then(setTemplates), [])
  const hasDesign = useStore((s) => s.design !== null)
  const name = useStore((s) => s.design?.name)
  const loads = useStore((s) => s.loads)
  const { loadTemplate, setName } = useStore.getState()

  return (
    <div className="grid h-full grid-rows-[auto_minmax(0,1fr)_auto_auto]">
      <TopBar>
        {name !== undefined && (
          <input
            aria-label="Design name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="min-w-0 rounded border border-transparent bg-transparent px-1 py-0.5 hover:border-border focus:border-accent"
          />
        )}
        <select
          aria-label="Load a template"
          value=""
          onChange={(e) => loadTemplate(e.target.value === 'blank' ? BLANK : templates[Number(e.target.value)])}
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

      <div className="grid min-h-0 grid-cols-[10rem_minmax(0,1fr)_18rem] overflow-hidden">
        {hasDesign ? (
          <Canvas key={loads} />
        ) : (
          <>
            <main className="col-span-2 min-h-0 bg-bg">
              <EmptyState templates={templates} onPick={loadTemplate} />
            </main>
            <aside className="border-l border-border bg-panel p-3 text-sm text-muted">
              Select a node to edit its parameters.
            </aside>
          </>
        )}
      </div>

      {hasDesign && <RunBar />}
      {hasDesign && <Dashboard />}
    </div>
  )
}
