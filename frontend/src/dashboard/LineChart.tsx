import { useId, useState, type KeyboardEvent, type PointerEvent } from 'react'

export interface Series { label: string; color: string; values: number[] }

// A small time-series chart shared by the latency and GPU tabs. The SVG stretches to fill its box
// (lines keep a 2px stroke via non-scaling-stroke); axis labels and the hover readout are HTML so
// text never stretches. One y-axis only: callers split different units into separate charts.
// Hover or focus + ←/→ moves a crosshair that reads out every series at that time. `markAt` draws
// playback's moment (the one the canvas shows) as a thin orange line.
export default function LineChart({ xs, series, format, max, summary, markAt }: {
  xs: number[] // seconds, evenly spaced
  series: Series[]
  format: (v: number) => string
  max?: number // fixed y-axis top (e.g. 1 for a share); otherwise rounded up from the data
  summary: string // the one-line text version of the chart (§11.3 accessibility)
  markAt?: number // seconds
}) {
  const [at, setAt] = useState<number | null>(null)
  const gid = useId().replace(/[^a-zA-Z0-9]/g, '') // usable inside url(#…)
  const top = max ?? niceCeil(Math.max(0, ...series.flatMap((s) => s.values)))
  const last = xs.length - 1
  const x = (i: number) => (last > 0 ? (i / last) * 1000 : 500)
  const y = (v: number) => 100 - (Math.min(v, top) / top) * 100
  const path = (vs: number[]) => vs.map((v, i) => `${i ? 'L' : 'M'}${x(i)},${y(v)}`).join('')
  const span = xs[last] - xs[0]
  const mark = markAt === undefined ? null : span > 0 ? Math.max(0, Math.min(1, (markAt - xs[0]) / span)) * 100 : 50

  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    setAt(Math.round(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * last))
  }
  const onKey = (e: KeyboardEvent) => {
    const step = { ArrowLeft: -1, ArrowRight: 1 }[e.key]
    if (step) setAt((i) => Math.max(0, Math.min(last, (i ?? 0) + step)))
  }

  return (
    <figure className="flex flex-col gap-2">
      <figcaption className="text-[13px]">{summary}</figcaption>
      {series.length > 1 && (
        <ul className="flex gap-4 text-xs text-muted">
          {series.map((s) => (
            <li key={s.label} className="flex items-center gap-1.5">
              <Key color={s.color} />
              {s.label}
            </li>
          ))}
        </ul>
      )}
      <div className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-2">
        <div className="num flex flex-col justify-between text-right text-xs text-muted" aria-hidden>
          <span>{format(top)}</span>
          <span>{format(top / 2)}</span>
          <span>{format(0)}</span>
        </div>
        <div
          className="relative h-40 touch-none rounded-lg"
          tabIndex={0}
          role="img"
          aria-label={summary}
          onPointerMove={onMove}
          onPointerLeave={() => setAt(null)}
          onKeyDown={onKey}
          onBlur={() => setAt(null)}
        >
          <svg viewBox="0 0 1000 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full overflow-visible">
            <defs>
              <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" style={{ stopColor: series.at(-1)!.color, stopOpacity: 0.16 }} />
                <stop offset="0.75" style={{ stopColor: series.at(-1)!.color, stopOpacity: 0 }} />
              </linearGradient>
            </defs>
            {[0, 50, 100].map((g) => (
              <line key={g} x1={0} x2={1000} y1={g} y2={g} stroke="var(--border)" strokeDasharray={g === 100 ? undefined : '3 5'} vectorEffect="non-scaling-stroke" />
            ))}
            {/* Only the last (hottest) series gets a lit area; stacked fills would muddy each other. */}
            <path d={`${path(series.at(-1)!.values)}L${x(last)},100L${x(0)},100Z`} fill={`url(#${gid})`} />
            {series.map((s) => (
              <path
                key={s.label} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round"
                vectorEffect="non-scaling-stroke" style={{ filter: `drop-shadow(0 0 6px color-mix(in srgb, ${s.color} 55%, transparent))` }}
              />
            ))}
          </svg>
          {mark !== null && <div className="pointer-events-none absolute inset-y-0 w-px bg-accent/70" style={{ left: `${mark}%` }} aria-hidden />}
          {at !== null && (
            <>
              <div className="pointer-events-none absolute inset-y-0 w-px bg-[linear-gradient(transparent,var(--muted),transparent)]" style={{ left: `${x(at) / 10}%` }} />
              {series.map((s) => (
                <span
                  key={s.label}
                  className="pointer-events-none absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-panel"
                  style={{ left: `${x(at) / 10}%`, top: `${y(s.values[at])}%`, background: s.color, boxShadow: `0 0 10px ${s.color}` }}
                />
              ))}
              <div
                className="pointer-events-none absolute top-0 z-10 rounded-xl border border-border-strong bg-panel-3/95 px-3 py-2 text-xs whitespace-nowrap shadow-[0_12px_30px_-10px_rgb(0_0_0/0.9)] backdrop-blur-sm"
                style={x(at) > 600 ? { right: `${100 - x(at) / 10}%`, marginRight: 12 } : { left: `${x(at) / 10}%`, marginLeft: 12 }}
              >
                <div className="num mb-1 text-muted">{xs[at]} s</div>
                {series.map((s) => (
                  <div key={s.label} className="flex items-center gap-2">
                    <Key color={s.color} />
                    <span className="num font-medium">{format(s.values[at])}</span>
                    <span className="text-muted">{s.label}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
        <div />
        <div className="num flex justify-between text-xs text-muted" aria-hidden>
          <span>{xs[0]} s</span>
          <span>{xs[last]} s</span>
        </div>
      </div>
    </figure>
  )
}

/** A series' legend key: a short stroke of its color, like the line it names. */
const Key = ({ color }: { color: string }) => <span className="h-0.5 w-3 rounded-full" style={{ background: color, boxShadow: `0 0 6px ${color}` }} />

/** Rounds up to 1, 2, or 5 × a power of ten, so the axis top reads cleanly. */
function niceCeil(v: number): number {
  if (v <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(v))
  return [1, 2, 5, 10].find((m) => m * p >= v)! * p
}
