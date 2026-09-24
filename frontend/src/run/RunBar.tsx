import { LoaderCircle, Play, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { estimateDesignRequests, rateAt } from '../lib/estimate'
import { count } from '../lib/format'
import { LIMITS } from '../lib/validate'
import { useStore } from '../store'
import type { Design, RunConfig } from '../api/api'

const WARMUP_S = 5 // §7.3 default; not exposed in the UI

// The run bar (§11.2): a sketch of the traffic, run length and seed, the request estimate, and Run.
// Playback lives on the canvas (PlaybackBar). Outside a text field, `R` runs and Space plays/pauses. The store ignores a run while one is
// in flight, so a double click or a held key can't start two.
export default function RunBar() {
  const { design, status, run, setDrawer, togglePlay } = useStore(
    useShallow((s) => ({ design: s.design!, status: s.status, run: s.run, setDrawer: s.setDrawer, togglePlay: s.togglePlay })),
  )
  const [durationS, setDuration] = useState(60)
  const [seed, setSeed] = useState(42)
  const config: RunConfig = { durationS, seed, warmupS: WARMUP_S }
  const requests = Math.round(estimateDesignRequests(design, durationS))
  const running = status === 'running'

  const start = () => {
    setDrawer({ open: true }) // so the result, or why the run was refused, is visible
    void run(config)
  }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (e.metaKey || e.ctrlKey || e.altKey || t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName)) return
      if (e.key === 'r' || e.key === 'R') start()
      else if (e.key === ' ' && t.tagName !== 'BUTTON') togglePlay() // a focused button already clicks on Space
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }) // no deps: re-bound each render so `start` always sees the current config

  return (
    <footer className="panel col-span-2 col-start-2 flex flex-wrap items-center gap-x-5 gap-y-3 px-4 py-3 text-[13px]">
      <Sparkline design={design} durationS={durationS} />
      <span className="h-8 w-px bg-border" aria-hidden />
      <label className="flex items-center gap-2 text-muted">
        Duration
        <span className="field flex h-9 items-center pr-3 focus-within:border-accent focus-within:shadow-[0_0_0_3px_rgb(255_106_43/0.18)]">
          <input
            type="number" min={LIMITS.minDurationS} max={LIMITS.maxDurationS} value={durationS}
            onChange={(e) => setDuration(e.target.valueAsNumber)}
            className="num w-16 bg-transparent pl-3 text-text outline-none"
          />
          <span className="text-muted">s</span>
        </span>
      </label>
      <label className="flex items-center gap-2 text-muted" title="Same design, duration and seed always give the same result.">
        Seed
        <input
          type="number" step={1} value={seed}
          onChange={(e) => setSeed(e.target.valueAsNumber)}
          className="field num h-9 w-20 px-3"
        />
      </label>
      <span className={`num flex items-center gap-1.5 text-xs ${requests > LIMITS.requests ? 'text-warn' : 'text-muted'}`}>
        {requests > LIMITS.requests && <TriangleAlert size={13} aria-hidden />}≈ {Number.isFinite(requests) ? count(requests) : '—'} requests
      </span>
      <button
        onClick={start}
        disabled={running}
        aria-busy={running}
        aria-keyshortcuts="R"
        title="Run (R)"
        className="btn-primary ml-auto flex h-10 items-center gap-2 pr-5 pl-4 text-[13px] disabled:cursor-wait disabled:opacity-70"
      >
        {running ? <LoaderCircle size={15} className="animate-spin" aria-hidden /> : <Play size={14} fill="currentColor" aria-hidden />}
        {running ? 'Running…' : 'Run'}
        {!running && <kbd className="num ml-1 rounded border border-black/15 px-1 text-[10px] font-normal text-black/50">R</kbd>}
      </button>
    </footer>
  )
}

/** Total arrival rate over the run, as a small lit area: the "traffic ▁▂▅▇▅▂" in §11.2. */
function Sparkline({ design, durationS }: { design: Design; durationS: number }) {
  const users = design.nodes.flatMap((n) => (n.kind === 'users' ? [n.params.traffic] : []))
  if (!users.length || !(durationS > 0)) return null
  const N = 48
  const rates = Array.from({ length: N + 1 }, (_, i) => users.reduce((s, t) => s + rateAt(t, (i / N) * durationS, durationS), 0))
  const peak = Math.max(...rates) || 1
  const line = rates.map((r, i) => `${(i / N) * 100},${22 - (r / peak) * 13}`).join(' ') // headroom, so flat traffic reads as a line
  return (
    <span className="flex items-center gap-3">
      <span className="flex flex-col leading-tight">
        <span className="text-xs text-muted">Traffic</span>
        <span className="num text-xs">≤ {count(peak)} req/s</span>
      </span>
      <svg viewBox="0 0 100 24" preserveAspectRatio="none" className="h-8 w-28" role="img" aria-label={`Traffic peaks at ${count(peak)} requests per second`}>
        <defs>
          <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" style={{ stopColor: 'var(--accent)', stopOpacity: 0.22 }} />
            <stop offset="1" style={{ stopColor: 'var(--accent)', stopOpacity: 0 }} />
          </linearGradient>
        </defs>
        <polygon points={`0,24 ${line} 100,24`} fill="url(#spark-fill)" />
        <polyline points={line} fill="none" stroke="var(--accent)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
      </svg>
    </span>
  )
}
