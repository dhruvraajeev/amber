import { useEffect, useState } from 'react'
import { getTemplates } from './api/api'
import Canvas from './canvas/Canvas'
import { BLANK } from './canvas/map'
import Dashboard from './dashboard/Dashboard'
import EmptyState from './layout/EmptyState'
import TopBar from './layout/TopBar'
import RunBar from './run/RunBar'
import { useStore } from './store'
import type { Design } from './types/contracts'

// The editor page: §11.2's regions as floating panels on the lit ground. Column 1 is the palette
// rail (rows 2–4); the canvas and inspector share row 2; the run bar and results sit beneath them.
// The design lives in the store (and is autosaved), so a refresh reopens it instead of the empty state.
export default function App() {
  const [templates, setTemplates] = useState<Design[]>([])
  useEffect(() => void getTemplates().then(setTemplates), [])
  const hasDesign = useStore((s) => s.design !== null)
  const name = useStore((s) => s.design?.name)
  const loads = useStore((s) => s.loads)
  const { loadTemplate, setName } = useStore.getState()

  return (
    <div className="grid h-full grid-cols-[4.5rem_minmax(0,1fr)_19rem] grid-rows-[auto_minmax(16rem,1fr)_auto_auto] gap-3 p-3">
      <TopBar className="col-span-3">
        {name !== undefined && (
          <input
            aria-label="Design name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="min-w-0 max-w-72 flex-1 truncate rounded-lg border border-transparent bg-transparent px-2 py-1.5 text-[15px] font-medium hover:border-border focus:border-accent focus:outline-none"
          />
        )}
        <select
          aria-label="Load a template"
          value=""
          onChange={(e) => loadTemplate(e.target.value === 'blank' ? BLANK : templates[Number(e.target.value)])}
          className="field h-9 rounded-full pl-3.5 text-[13px] text-muted"
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

      {hasDesign ? (
        <Canvas key={loads} />
      ) : (
        <main className="col-span-3 row-span-3 min-h-0">
          <EmptyState templates={templates} onPick={loadTemplate} />
        </main>
      )}

      {hasDesign && <RunBar />}
      {hasDesign && <Dashboard />}
    </div>
  )
}
