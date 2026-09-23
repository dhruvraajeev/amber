import { useEffect, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { estimateDesignRequests, rateAt } from '../lib/estimate'
import { count } from '../lib/format'
import { LIMITS } from '../lib/validate'
import { useStore } from '../store'
import type { Design, RunConfig } from '../types/contracts'

const WARMUP_S = 5 // §7.3 default; not exposed in the UI

// The run bar (§11.2): a sketch of the traffic, run length and seed, the request estimate, and Run.
// `R` anywhere outside a text field runs too. The store ignores a run while one is in flight, so a
// double click or a held key can't start two.
export default function RunBar() {
  const { design, status, run, setDrawer } = useStore(
    useShallow((s) => ({ design: s.design!, status: s.status, run: s.run, setDrawer: s.setDrawer })),
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
      if (e.key !== 'r' && e.key !== 'R') return
      if (e.metaKey || e.ctrlKey || e.altKey || t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName)) return
      e.preventDefault()
      start()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }) // no deps: re-bound each render so `start` always sees the current config

  return (
    <footer className="flex flex-wrap items-center gap-4 border-t border-border bg-panel px-4 py-2 text-sm">
      <Sparkline design={design} durationS={durationS} />
      <label className="flex items-center gap-2 text-muted">
        Duration
        <input
          type="number" min={LIMITS.minDurationS} max={LIMITS.maxDurationS} value={durationS}
          onChange={(e) => setDuration(e.target.valueAsNumber)}
          className="num w-20 rounded border border-border bg-panel-2 px-2 py-1 text-text"
        />
        s
      </label>
      <label className="flex items-center gap-2 text-muted" title="Same design, duration and seed always give the same result.">
        Seed
        <input
          type="number" step={1} value={seed}
          onChange={(e) => setSeed(e.target.valueAsNumber)}
          className="num w-20 rounded border border-border bg-panel-2 px-2 py-1 text-text"
        />
      </label>
      <span className={`num ${requests > LIMITS.requests ? 'text-warn' : 'text-muted'}`}>
        {requests > LIMITS.requests && '⚠ '}≈ {Number.isFinite(requests) ? count(requests) : '—'} requests
      </span>
      <button
        onClick={start}
        disabled={running}
        aria-busy={running}
        aria-keyshortcuts="R"
        title="Run (R)"
        className="ml-auto rounded bg-accent px-4 py-1.5 font-semibold text-bg hover:bg-accent-2 disabled:cursor-wait disabled:opacity-60"
      >
        {running ? 'Running…' : '▶ Run'}
      </button>
    </footer>
  )
}

/** Total arrival rate over the run, as a tiny line: the "traffic ▁▂▅▇▅▂" in §11.2. */
function Sparkline({ design, durationS }: { design: Design; durationS: number }) {
  const users = design.nodes.flatMap((n) => (n.kind === 'users' ? [n.params.traffic] : []))
  if (!users.length || !(durationS > 0)) return null
  const N = 48
  const rates = Array.from({ length: N + 1 }, (_, i) => users.reduce((s, t) => s + rateAt(t, (i / N) * durationS, durationS), 0))
  const peak = Math.max(...rates) || 1
  const points = rates.map((r, i) => `${(i / N) * 100},${20 - (r / peak) * 18}`).join(' ')
  return (
    <span className="flex items-center gap-2 text-muted">
      Traffic
      <svg viewBox="0 0 100 20" preserveAspectRatio="none" className="h-5 w-24" role="img" aria-label={`Traffic peaks at ${count(peak)} requests per second`}>
        <polyline points={points} fill="none" stroke="var(--accent)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
      </svg>
      <span className="num text-xs">≤ {count(peak)} req/s</span>
    </span>
  )
}
