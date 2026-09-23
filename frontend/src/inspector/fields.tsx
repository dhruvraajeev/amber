import type { ReactNode } from 'react'
import type { LatencyDist } from '../types/contracts'

// The field kit (§11.6). Every field takes a one-sentence `help` (shown on hover) and an
// optional `error` from the validator, rendered inline under the control.

/** Looks up the validator's message for a path under `params`, e.g. "work" or "traffic.rps". */
export type Errors = (path: string) => string | undefined

/** What every per-kind form receives. */
export interface FormProps<P> { params: P; set: (params: P) => void; err: Errors }

const input = 'w-full rounded border bg-panel-2 px-2 py-1 text-sm'
const border = (error?: string) => (error ? 'border-crit' : 'border-border')

function Row({ label, help, error, children }: { label: string; help: string; error?: string; children: ReactNode }) {
  return (
    <label className="block" title={help}>
      <span className="mb-1 block text-xs text-muted">{label}</span>
      {children}
      {error && (
        <span role="alert" className="mt-1 block text-xs text-warn">
          ⚠ {error}
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
      className={`num ${input} ${border(error)}`}
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
      <span className="flex items-center gap-2">
        <input
          type="range" min={0} max={1} step={0.01} value={p.value}
          onChange={(e) => p.onChange(e.target.valueAsNumber)}
          className="flex-1 accent-accent"
        />
        <span className="num w-10 text-right text-sm">{Math.round(p.value * 100)}%</span>
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
      <select value={p.value} onChange={(e) => p.onChange(e.target.value as T)} className={`${input} ${border(p.error)}`}>
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
    <label className="flex items-center gap-2 text-sm" title={p.help}>
      <input type="checkbox" checked={p.value} onChange={(e) => p.onChange(e.target.checked)} className="accent-accent" />
      {p.label}
    </label>
  )
}

export function TextField(p: { label: string; help: string; value: string; onChange: (v: string) => void; error?: string }) {
  return (
    <Row label={p.label} help={p.help} error={p.error}>
      <input value={p.value} onChange={(e) => p.onChange(e.target.value)} className={`${input} ${border(p.error)}`} />
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
          <span key={k} className="flex items-center gap-1">
            <span className="text-xs text-muted">{k.slice(0, 3)}</span>
            <Num value={d[k]} onChange={(v) => p.onChange({ ...d, [k]: v })} error={p.error} />
          </span>
        ))}
      </span>
    </Row>
  )
}
