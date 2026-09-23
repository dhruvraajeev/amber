import { type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { count, ms, pct, rps, usd } from '../lib/format'
import { useStore } from '../store'
import type { DashboardTab } from '../store/uiSlice'
import type { RunResult } from '../types/contracts'
import Attribution from './Attribution'
import Bottlenecks from './Bottlenecks'
import CostCard from './CostCard'
import GpuChart from './GpuChart'
import LatencyChart from './LatencyChart'
import LoadBars from './LoadBars'

const TABS: { id: DashboardTab; name: string }[] = [
  { id: 'summary', name: 'Summary' },
  { id: 'latency', name: 'Latency' },
  { id: 'load', name: 'Load' },
  { id: 'gpu', name: 'GPU' },
  { id: 'cost', name: 'Cost' },
  { id: 'bottlenecks', name: 'Bottlenecks' },
  { id: 'attribution', name: 'Where slow requests spend time' },
]
const MIN_HEIGHT = 120

// The results drawer (§11.2): tabs over the latest RunResult. Drag or arrow-key the top edge to resize.
// While a new run is in flight (or was refused) the previous result stays up, dimmed, so the layout doesn't jump.
export default function Dashboard() {
  const { status, result, issues, open, height, tab, setDrawer, setTab, select, design } = useStore(
    useShallow((s) => ({
      status: s.status, result: s.result, issues: s.issues, open: s.drawerOpen, height: s.drawerHeight,
      tab: s.tab, setDrawer: s.setDrawer, setTab: s.setTab, select: s.select, design: s.design,
    })),
  )
  // Results name nodes by id; show the current label, or the id if the node has since been deleted.
  const label = (id: string) => design?.nodes.find((n) => n.id === id)?.label ?? id
  const resize = (h: number) => setDrawer({ height: Math.round(Math.max(MIN_HEIGHT, Math.min(window.innerHeight * 0.7, h))) })

  const onDragStart = (e: PointerEvent) => {
    const [y0, h0] = [e.clientY, height]
    const move = (m: globalThis.PointerEvent) => resize(h0 + y0 - m.clientY)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', () => window.removeEventListener('pointermove', move), { once: true })
  }
  const onResizeKey = (e: KeyboardEvent) => {
    const step = { ArrowUp: 24, ArrowDown: -24 }[e.key]
    if (step) resize(height + step)
  }

  return (
    <section aria-label="Results" className="flex flex-col border-t border-border bg-panel" style={open ? { height } : undefined}>
      {open && (
        <div
          role="separator"
          aria-orientation="horizontal"
          aria-label="Resize results"
          tabIndex={0}
          onPointerDown={onDragStart}
          onKeyDown={onResizeKey}
          className="-mt-1 h-2 shrink-0 cursor-row-resize hover:bg-accent/30 focus-visible:bg-accent/30"
        />
      )}
      <div className="flex shrink-0 items-center gap-1 overflow-x-auto px-3" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => { setTab(t.id); setDrawer({ open: true }) }}
            className={`border-b-2 px-2 py-1.5 text-sm whitespace-nowrap ${tab === t.id ? 'border-accent text-text' : 'border-transparent text-muted hover:text-text'}`}
          >
            {t.name}
          </button>
        ))}
        <button
          onClick={() => setDrawer({ open: !open })}
          aria-expanded={open}
          className="ml-auto px-2 text-sm text-muted hover:text-text"
        >
          {open ? 'Hide ▾' : 'Show ▴'}
        </button>
      </div>
      {open && (
        <div role="tabpanel" className="min-h-0 flex-1 overflow-y-auto px-4 pt-2 pb-4">
          {status === 'error' && <RunError issues={issues} />}
          {result && (
            <div className={`transition-opacity ${status === 'done' ? '' : 'opacity-50'}`} aria-busy={status === 'running'}>
              {body(tab, result, label, select)}
            </div>
          )}
          {!result && status !== 'error' && (
            <p className="text-sm text-muted">
              {status === 'running' ? 'Running the simulation…' : 'Run a simulation to see results. Press R or click Run.'}
            </p>
          )}
        </div>
      )}
    </section>
  )
}

function body(tab: DashboardTab, result: RunResult, label: (id: string) => string, select: (id: string) => void) {
  switch (tab) {
    case 'summary': return <Summary result={result} />
    case 'latency': return <LatencyChart result={result} />
    case 'load': return <LoadBars result={result} label={label} />
    case 'gpu': return <GpuChart result={result} label={label} />
    case 'cost': return <CostCard result={result} label={label} />
    case 'bottlenecks': return <Bottlenecks result={result} onSelect={select} />
    case 'attribution': return <Attribution result={result} label={label} />
  }
}

function RunError({ issues }: { issues: { message: string }[] }) {
  return (
    <div role="alert" className="mb-3 rounded border border-crit bg-panel-2 px-3 py-2 text-sm">
      <p><span className="text-warn">⚠</span> {issues.length ? 'Can’t run yet:' : 'The run failed. Try again.'}</p>
      {issues.length > 0 && (
        <ul className="mt-1 list-disc pl-5">
          {issues.map((i, n) => <li key={n}>{i.message}</li>)}
        </ul>
      )}
    </div>
  )
}

function Summary({ result: r }: { result: RunResult }) {
  const s = r.summary
  const worst = r.bottlenecks.find((b) => b.severity !== 'info')
  // Every way a request can fail, skipping the ones that didn't happen. `errors` = rejected + rate-limited.
  const failures: [number, string][] = [[s.rejected, 'rejected'], [s.errors - s.rejected, 'rate-limited'], [s.timeouts, 'timed out']]
  const lost = failures.filter(([n]) => n > 0).map(([n, what]) => `${count(n)} ${what}`)
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm">
        {count(s.completed)} of {count(s.requests)} requests succeeded; p99 latency was {ms(s.latencyMs.p99)}. {worst?.message}
      </p>
      <dl className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-2">
        <Tile label="Requests" value={count(s.requests)} sub={`after ${r.config.warmupS} s warmup`} />
        <Tile label="Throughput" value={rps(s.throughputRps)} sub="completed" />
        <Tile label="Error rate" value={pct(s.errorRate, 1)} sub={lost.join(' · ') || 'no failures'} />
        <Tile label="Latency p99" value={ms(s.latencyMs.p99)} sub={`p50 ${ms(s.latencyMs.p50)} · p95 ${ms(s.latencyMs.p95)}`} />
        {s.ttftMs && <Tile label="Time to first token" value={ms(s.ttftMs.p50)} sub={`p50 · p99 ${ms(s.ttftMs.p99)}`} />}
        <Tile label="Monthly cost" value={usd(r.cost.monthlyTotalUsd)} sub="estimate" />
      </dl>
      <p className="num text-xs text-muted">
        Simulated {count(r.engine.simulatedRequests)} requests over {r.config.durationS} s (seed {r.config.seed}) in {count(r.engine.wallMs)} ms.
      </p>
    </div>
  )
}

function Tile({ label, value, sub }: { label: string; value: ReactNode; sub: string }) {
  return (
    <div className="rounded border border-border bg-panel-2 px-3 py-2">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="num text-lg">{value}</dd>
      <dd className="num text-xs text-muted">{sub}</dd>
    </div>
  )
}
