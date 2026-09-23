import { Link } from 'react-router'
import TopBar from '../layout/TopBar'
import { configDiff, delta, METRICS, type Verdict } from '../lib/metrics'
import { useStore } from '../store'
import type { RunResult } from '../types/contracts'

const VERDICT: Record<Verdict, { word: string; className: string }> = {
  better: { word: 'better', className: 'text-ok' },
  worse: { word: 'worse', className: 'text-warn' },
  same: { word: 'same', className: 'text-muted' },
}
const SETTING = { durationS: 'duration', seed: 'seed', warmupS: 'warmup' }

// /compare (§11.1): the two most recently pinned runs side by side. B is the newer pin; every change
// reads "B compared with A". Pins live in memory, so a page refresh clears them.
export default function CompareView() {
  const pinned = useStore((s) => s.pinned)
  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <main className="flex-1 overflow-auto p-4">
        <div className="mx-auto max-w-3xl rounded-lg border border-border bg-panel p-6">
          <h1 className="text-lg font-semibold">Compare runs</h1>
          {pinned.length < 2 ? (
            <p className="mt-2 text-muted">
              {pinned.length === 1 ? 'One run pinned. ' : ''}Pin two runs from the results drawer to compare them here.{' '}
              <Link to="/" className="text-accent hover:text-accent-2">Back to the editor</Link>
            </p>
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
      <p className="mt-1 text-sm text-muted">
        {a.designHash === b.designHash ? 'Same design in both runs.' : 'The design changed between the two runs.'}
      </p>
      {differs.length > 0 && (
        <p role="alert" className="mt-3 rounded border border-warn bg-panel-2 px-3 py-2 text-sm">
          <span className="text-warn" aria-hidden>⚠</span> These runs used different settings (
          {differs.map((k) => `${SETTING[k]} ${a.config[k]} vs ${b.config[k]}`).join(', ')}), so some of the
          difference comes from the settings, not the design.
        </p>
      )}
      <table className="num mt-4 w-full text-sm">
        <thead className="text-left text-xs text-muted">
          <tr>
            <th className="py-1 font-normal">Metric</th>
            <th className="py-1 text-right font-normal">A <span className="block">{config(a)}</span></th>
            <th className="py-1 text-right font-normal">B <span className="block">{config(b)}</span></th>
            <th className="py-1 text-right font-normal">B vs A</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ m, va, vb, d }) => (
            <tr key={m.name} className="border-t border-border">
              <td className="py-2 font-sans">{m.name}</td>
              <td className="py-2 text-right">{m.format(va)}</td>
              <td className="py-2 text-right">{m.format(vb)}</td>
              <td className="py-2 text-right">
                {d.verdict === 'same' ? '—' : `${d.abs > 0 ? '+' : '−'}${(m.formatDelta ?? m.format)(Math.abs(d.abs))}`}
                {d.rel !== null && d.verdict !== 'same' && <span className="text-muted"> ({d.rel > 0 ? '+' : '−'}{Math.abs(d.rel * 100).toFixed(1)}%)</span>}{' '}
                <span className={`font-sans text-xs ${VERDICT[d.verdict].className}`}>{VERDICT[d.verdict].word}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

const config = (r: RunResult) => `${r.config.durationS} s · seed ${r.config.seed}`
