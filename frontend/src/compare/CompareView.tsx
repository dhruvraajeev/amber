import { ArrowLeft, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router'
import TopBar from '../layout/TopBar'
import { configDiff, delta, METRICS, type Verdict } from '../lib/metrics'
import { useStore } from '../store'
import type { RunResult } from '../types/contracts'

const VERDICT: Record<Verdict, { word: string; className: string }> = {
  better: { word: 'better', className: 'border-ok/30 bg-ok/10 text-ok' },
  worse: { word: 'worse', className: 'border-warn/35 bg-warn/10 text-warn' },
  same: { word: 'same', className: 'border-border text-muted' },
}
const SETTING = { durationS: 'duration', seed: 'seed', warmupS: 'warmup' }

// /compare (§11.1): the two most recently pinned runs side by side. B is the newer pin; every change
// reads "B compared with A". Pins live in memory, so a page refresh clears them.
export default function CompareView() {
  const pinned = useStore((s) => s.pinned)
  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <TopBar />
      <main className="min-h-0 flex-1 overflow-auto">
        <div className="panel mx-auto max-w-4xl p-6 sm:p-8">
          <h1 className="text-2xl font-semibold tracking-[-0.02em]">Compare runs</h1>
          {pinned.length < 2 ? (
            <div className="mt-2 text-muted">
              <p>{pinned.length === 1 ? 'One run pinned. ' : ''}Pin two runs from the results drawer to compare them here.</p>
              <Link to="/" className="field mt-5 inline-flex h-10 items-center gap-2 rounded-full px-4 text-[13px] text-text">
                <ArrowLeft size={15} aria-hidden />
                Back to the editor
              </Link>
            </div>
          ) : (
            <Table a={pinned[0]} b={pinned[1]} />
          )}
        </div>
      </main>
    </div>
  )
}

function Table({ a, b }: { a: RunResult; b: RunResult }) {
  const differs = configDiff(a.config, b.config)
  const rows = METRICS.flatMap((m) => {
    const [va, vb] = [m.get(a), m.get(b)]
    return va === undefined || vb === undefined ? [] : [{ m, va, vb, d: delta(m, va, vb) }]
  })
  return (
    <>
      <p className="mt-1 text-[13px] text-muted">
        {a.designHash === b.designHash ? 'Same design in both runs.' : 'The design changed between the two runs.'}
      </p>
      {differs.length > 0 && (
        <p role="alert" className="mt-4 flex gap-3 rounded-xl border border-warn/35 bg-warn/[0.06] px-4 py-3 text-[13px]">
          <TriangleAlert size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden />
          <span>These runs used different settings (
          {differs.map((k) => `${SETTING[k]} ${a.config[k]} vs ${b.config[k]}`).join(', ')}), so some of the
          difference comes from the settings, not the design.</span>
        </p>
      )}
      <table className="num mt-6 w-full text-[13px]">
        <thead className="text-left text-xs text-muted">
          <tr>
            <th className="pb-3 font-sans font-normal">Metric</th>
            <th className="pb-3 text-right font-normal"><span className="font-sans text-sm text-text">Run A</span><span className="block">{config(a)}</span></th>
            <th className="pb-3 text-right font-normal"><span className="font-sans text-sm text-text">Run B</span><span className="block">{config(b)}</span></th>
            <th className="pb-3 text-right font-sans font-normal">B vs A</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ m, va, vb, d }) => (
            <tr key={m.name} className="border-t border-border transition-colors hover:bg-panel-2/60">
              <td className="py-3 font-sans">{m.name}</td>
              <td className="py-3 text-right text-muted">{m.format(va)}</td>
              <td className="py-3 text-right">{m.format(vb)}</td>
              <td className="py-3 text-right">
                {d.verdict === 'same' ? '—' : `${d.abs > 0 ? '+' : '−'}${(m.formatDelta ?? m.format)(Math.abs(d.abs))}`}
                {d.rel !== null && d.verdict !== 'same' && <span className="text-muted"> ({d.rel > 0 ? '+' : '−'}{Math.abs(d.rel * 100).toFixed(1)}%)</span>}{' '}
                <span className={`ml-1 inline-block rounded-full border px-2 py-0.5 font-sans text-[11px] ${VERDICT[d.verdict].className}`}>{VERDICT[d.verdict].word}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

const config = (r: RunResult) => `${r.config.durationS} s · seed ${r.config.seed}`
