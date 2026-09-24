import { TriangleAlert } from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'
import type { LatencyDist } from '../api/api'

// The field kit (§11.6). Every field takes a one-sentence `help` (shown on hover) and an
// optional `error` from the validator, rendered inline under the control.

/** Looks up the validator's message for a path under `params`, e.g. "work" or "traffic.rps". */
export type Errors = (path: string) => string | undefined

/** What every per-kind form receives. */
export interface FormProps<P> { params: P; set: (params: P) => void; err: Errors }

const input = 'field h-9 w-full px-3 text-[13px]'

function Row({ label, help, error, children }: { label: string; help: string; error?: string; children: ReactNode }) {
  return (
    <label className="block" title={help}>
      <span className="mb-1.5 block text-xs text-muted">{label}</span>
      {children}
      {error && (
        <span role="alert" className="mt-1.5 flex items-start gap-1.5 text-xs text-warn">
          <TriangleAlert size={13} className="mt-px shrink-0" aria-hidden />
          {error}
        </span>
      )}
    </label>
  )
}

// An emptied field becomes NaN; the validator flags it until a number is typed back in.
function Num({ value, onChange, error, step }: { value: number; onChange: (v: number) => void; error?: string; step?: number }) {
  return (
    <input
      type="number"
      step={step ?? 'any'}
      value={Number.isFinite(value) ? value : ''}
      onChange={(e) => onChange(e.target.valueAsNumber)}
      aria-invalid={!!error}
      className={`num ${input}`}
    />
  )
}

export function NumberField(p: { label: string; help: string; unit?: string; value: number; onChange: (v: number) => void; error?: string; step?: number }) {
  return (
    <Row label={p.unit ? `${p.label} (${p.unit})` : p.label} help={p.help} error={p.error}>
      <Num value={p.value} onChange={p.onChange} error={p.error} step={p.step} />
    </Row>
  )
}

/** A 0..1 value shown as a percentage. */
export function SliderField(p: { label: string; help: string; value: number; onChange: (v: number) => void; error?: string }) {
  return (
    <Row label={p.label} help={p.help} error={p.error}>
      <span className="flex items-center gap-3">
        <input
          type="range" min={0} max={1} step={0.01} value={p.value}
          onChange={(e) => p.onChange(e.target.valueAsNumber)}
          style={{ '--fill': `${p.value * 100}%` } as CSSProperties}
          className="flex-1"
        />
        <span className="num w-10 text-right text-[13px]">{Math.round(p.value * 100)}%</span>
      </span>
    </Row>
  )
}

/** With `placeholder`, the select shows it and acts as a one-shot action (e.g. "Fill from preset…"). */
export function SelectField<T extends string>(p: {
  label: string; help: string; value: T | ''; options: { value: T; label: string }[]
  onChange: (v: T) => void; error?: string; placeholder?: string
}) {
  return (
    <Row label={p.label} help={p.help} error={p.error}>
      <select value={p.value} onChange={(e) => p.onChange(e.target.value as T)} aria-invalid={!!p.error} className={input}>
        {p.placeholder && <option value="" disabled>{p.placeholder}</option>}
        {p.options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </Row>
  )
}

export function ToggleField(p: { label: string; help: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 text-[13px]" title={p.help}>
      {p.label}
      <input type="checkbox" role="switch" checked={p.value} onChange={(e) => p.onChange(e.target.checked)} className="peer sr-only" />
      <span
        aria-hidden
        className="relative h-5 w-9 shrink-0 rounded-full border border-border-strong bg-panel-3 transition-colors peer-checked:border-accent/60 peer-checked:bg-accent/80 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent after:absolute after:top-[2px] after:left-[2px] after:size-3.5 after:rounded-full after:bg-text after:transition-transform peer-checked:after:translate-x-4"
      />
    </label>
  )
}

export function TextField(p: { label: string; help: string; value: string; onChange: (v: string) => void; error?: string }) {
  return (
    <Row label={p.label} help={p.help} error={p.error}>
      <input value={p.value} onChange={(e) => p.onChange(e.target.value)} aria-invalid={!!p.error} className={input} />
    </Row>
  )
}

/** A p50/p99 latency pair in ms. The validator's "p99 ≥ p50" message shows under both. */
export function DistField(p: { label: string; help: string; value: LatencyDist; onChange: (v: LatencyDist) => void; error?: string }) {
  const { value: d } = p
  return (
    <Row label={`${p.label} (ms)`} help={p.help} error={p.error}>
      <span className="grid grid-cols-2 gap-2">
        {(['p50Ms', 'p99Ms'] as const).map((k) => (
          <span key={k} className="flex items-center gap-2">
            <span className="num text-[11px] text-muted">{k.slice(0, 3)}</span>
            <Num value={d[k]} onChange={(v) => p.onChange({ ...d, [k]: v })} error={p.error} />
          </span>
        ))}
      </span>
    </Row>
  )
}
