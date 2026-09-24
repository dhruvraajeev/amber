import { ArrowRight, ChevronDown, ChevronUp, Pin, PinOff, TriangleAlert } from 'lucide-react'
import { type KeyboardEvent, type PointerEvent } from 'react'
import { Link } from 'react-router'
import { useShallow } from 'zustand/react/shallow'
import { count, ms, pct, rps, usd } from '../lib/format'
import { useCountUp } from '../lib/useCountUp'
import { useStore } from '../store'
import type { DashboardTab } from '../store/uiSlice'
import type { RunResult } from '../api/api'
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
const MIN_HEIGHT = 140

// The results drawer (§11.2): tabs over the latest RunResult. Drag or arrow-key the top edge to resize.
// While a new run is in flight (or was refused) the previous result stays up, dimmed, so the layout doesn't jump.
export default function Dashboard() {
  const { status, result, issues, open, height, tab, setDrawer, setTab, select, design, pinned, pin } = useStore(
    useShallow((s) => ({
      status: s.status, result: s.result, issues: s.issues, open: s.drawerOpen, height: s.drawerHeight,
      tab: s.tab, setDrawer: s.setDrawer, setTab: s.setTab, select: s.select, design: s.design, pinned: s.pinned, pin: s.pin,
    })),
  )
  const isPinned = !!result && pinned.includes(result)
  // Results name nodes by id; show the current label, or the id if the node has since been deleted.
  const label = (id: string) => design?.nodes.find((n) => n.id === id)?.label ?? id
  const resize = (h: number) => setDrawer({ height: Math.round(Math.max(MIN_HEIGHT, Math.min(window.innerHeight * 0.6, h))) })

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
    <section
      aria-label="Results"
      className="panel col-span-2 col-start-2 flex flex-col"
      style={open ? { height: `min(${height}px, 45vh)` } : undefined}
    >
      {open && (
        <div
          role="separator"
          aria-orientation="horizontal"
          aria-label="Resize results"
          tabIndex={0}
          onPointerDown={onDragStart}
          onKeyDown={onResizeKey}
          className="group absolute inset-x-0 -top-1.5 z-10 flex h-3 cursor-row-resize justify-center focus-visible:outline-none"
        >
          <span className="mt-1 h-1 w-10 rounded-full bg-border-strong transition-colors group-hover:bg-accent group-focus-visible:bg-accent" />
        </div>
      )}
      <div className="flex shrink-0 items-center gap-3 px-3 pt-3 pb-2">
        <div className="segmented min-w-0 overflow-x-auto" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => { setTab(t.id); setDrawer({ open: true }) }}
              className="rounded-full px-3.5 py-1.5 text-[13px] whitespace-nowrap text-muted transition-colors hover:text-text aria-selected:text-text"
            >
              {t.name}
            </button>
          ))}
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2 text-[13px] whitespace-nowrap">
          {result && status === 'done' && (
            <button
              onClick={pin}
              disabled={isPinned}
              title="Keep this run to compare against another (the last two pins are kept)"
              className="field flex h-8 items-center gap-1.5 rounded-full px-3 text-text disabled:text-muted"
            >
              {isPinned ? <PinOff size={14} aria-hidden /> : <Pin size={14} className="text-accent" aria-hidden />}
              {isPinned ? 'Pinned' : 'Pin for compare'}
            </button>
          )}
          {pinned.length === 2 && (
            <Link to="/compare" className="flex h-8 items-center gap-1.5 rounded-full px-3 text-accent-2 hover:text-accent">
              Compare
              <ArrowRight size={14} aria-hidden />
            </Link>
          )}
          <button
            onClick={() => setDrawer({ open: !open })}
            aria-expanded={open}
            aria-label={open ? 'Hide results' : 'Show results'}
            className="btn-icon size-8"
          >
            {open ? <ChevronDown size={15} aria-hidden /> : <ChevronUp size={15} aria-hidden />}
          </button>
        </div>
      </div>
      {open && (
        <div role="tabpanel" className="min-h-0 flex-1 overflow-y-auto px-4 pt-2 pb-4">
          {status === 'error' && <RunError issues={issues} />}
          {result && (
            <div className={`transition-opacity duration-200 ${status === 'done' ? '' : 'opacity-50'}`} aria-busy={status === 'running'}>
              {body(tab, result, label, select)}
            </div>
          )}
          {!result && status !== 'error' && (
            status === 'running' ? <Skeleton /> : (
              <p className="flex h-full items-center justify-center gap-2 text-[13px] text-muted">
                Run a simulation to see results. Press
                <kbd className="num rounded-md border border-border-strong bg-panel-2 px-1.5 py-0.5 text-[11px] text-text">R</kbd>
                or click Run.
              </p>
            )
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

/** First run in flight: the tile grid's shape, shimmering, so the drawer doesn't jump when it lands. */
function Skeleton() {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(11rem,1fr))] gap-3" aria-label="Running the simulation…" role="status">
      {Array.from({ length: 5 }, (_, i) => (
        <div key={i} className="h-24 animate-pulse rounded-xl border border-border bg-panel-2" />
      ))}
    </div>
  )
}

function RunError({ issues }: { issues: { message: string }[] }) {
  return (
    <div role="alert" className="mb-3 flex gap-3 rounded-xl border border-crit/40 bg-crit/[0.07] px-4 py-3 text-[13px]">
      <TriangleAlert size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden />
      <div>
        <p className="font-medium">{issues.length ? 'Can’t run yet:' : 'The run failed. Try again.'}</p>
        {issues.length > 0 && (
          <ul className="mt-1 list-disc pl-4 text-muted marker:text-crit">
            {issues.map((i, n) => <li key={n}>{i.message}</li>)}
          </ul>
        )}
      </div>
    </div>
  )
}

function Summary({ result: r }: { result: RunResult }) {
  const s = r.summary
  const worst = r.bottlenecks.find((b) => b.severity !== 'info')
  // Every way a request can fail, skipping the ones that didn't happen. `errors` = rejected + rate-limited.
  const failures: [number, string][] = [[s.rejected, 'rejected'], [s.errors - s.rejected, 'rate-limited'], [s.timeouts, 'timed out']]
  const lost = failures.filter(([n]) => n > 0).map(([n, what]) => `${count(n)} ${what}`)
  // The summary counts each post-warmup arrival once with its own outcome; the rest were cut off by the end.
  const running = s.requests - s.completed - s.errors - s.timeouts
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-muted">
        <span className="text-text">{count(s.completed)} of {count(s.requests)} requests succeeded{running > 0 && `, ${count(running)} still running when the run ended`}; p99 latency was {ms(s.latencyMs.p99)}.</span> {worst?.message}
      </p>
      <dl className="grid grid-cols-[repeat(auto-fill,minmax(11rem,1fr))] gap-3">
        <Tile label="Requests" value={s.requests} format={count} sub={`after ${r.config.warmupS} s warmup`} />
        <Tile label="Throughput" value={s.throughputRps} format={rps} sub="completed" />
        <Tile label="Error rate" value={s.errorRate} format={(v) => pct(v, 1)} sub={lost.join(' · ') || 'no failures'} tone={s.errorRate > 0.01 ? 'crit' : undefined} />
        <Tile label="Latency p99" value={s.latencyMs.p99} format={ms} sub={`p50 ${ms(s.latencyMs.p50)} · p95 ${ms(s.latencyMs.p95)}`} />
        {s.ttftMs && <Tile label="Time to first token" value={s.ttftMs.p50} format={ms} sub={`p50 · p99 ${ms(s.ttftMs.p99)}`} />}
        <Tile label="Monthly cost" value={r.cost.monthlyTotalUsd} format={usd} sub="estimate" />
      </dl>
      <p className="num text-[11px] text-muted">
        Simulated {count(r.engine.simulatedRequests)} requests over {r.config.durationS} s (seed {r.config.seed}) in {count(r.engine.wallMs)} ms.
      </p>
    </div>
  )
}

/** One headline number that counts up when a run lands. `tone: 'crit'` adds a red edge, backed by the sub-line's words. */
function Tile({ label, value, format, sub, tone }: { label: string; value: number; format: (v: number) => string; sub: string; tone?: 'crit' }) {
  const shown = useCountUp(value)
  return (
    <div className={`spotlight overflow-hidden rounded-xl border bg-panel-2 px-4 py-3 ${tone === 'crit' ? 'border-crit/50' : 'border-border'}`}>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="figure mt-1 text-[22px] font-semibold leading-tight">{format(shown)}</dd>
      <dd className="num mt-1 truncate text-[11px] text-muted" title={sub}>{sub}</dd>
    </div>
  )
}
