import type { TrafficProfile, UsersParams } from '../../api/api'
import { NumberField, SelectField, type FormProps } from '../fields'

const TYPES = [
  { value: 'constant', label: 'Constant' },
  { value: 'spike', label: 'Spike' },
  { value: 'ramp', label: 'Ramp' },
] as const

// Switching shape keeps the current base rate and starts the new shape at 4× it.
function reshape(t: TrafficProfile, type: TrafficProfile['type']): TrafficProfile {
  const base = t.type === 'constant' ? t.rps : t.type === 'spike' ? t.baseRps : t.startRps
  if (type === 'constant') return { type, rps: base }
  if (type === 'spike') return { type, baseRps: base, peakRps: base * 4, peakStartS: 20, peakDurationS: 10 }
  return { type, startRps: base, endRps: base * 4 }
}

export default function UsersForm({ params: p, set, err }: FormProps<UsersParams>) {
  const t = p.traffic
  const rate = (key: string, label: string, help: string, value: number) => (
    <NumberField
      label={label} unit={key.endsWith('S') ? 's' : 'req/s'} help={help} value={value}
      onChange={(v) => set({ ...p, traffic: { ...t, [key]: v } as TrafficProfile })}
      error={err(`traffic.${key}`)}
    />
  )
  return (
    <>
      <SelectField
        label="Traffic shape" help="How the request rate changes over the run." value={t.type} options={[...TYPES]}
        onChange={(type) => set({ ...p, traffic: reshape(t, type) })}
      />
      {t.type === 'constant' && rate('rps', 'Rate', 'Requests per second, steady for the whole run.', t.rps)}
      {t.type === 'spike' && (
        <>
          {rate('baseRps', 'Base rate', 'Requests per second outside the spike.', t.baseRps)}
          {rate('peakRps', 'Peak rate', 'Requests per second during the spike.', t.peakRps)}
          {rate('peakStartS', 'Spike starts at', 'Seconds into the run when the spike begins.', t.peakStartS)}
          {rate('peakDurationS', 'Spike lasts', 'How many seconds the spike lasts.', t.peakDurationS)}
        </>
      )}
      {t.type === 'ramp' && (
        <>
          {rate('startRps', 'Start rate', 'Requests per second at the start of the run.', t.startRps)}
          {rate('endRps', 'End rate', 'Requests per second at the end; it rises in a straight line.', t.endRps)}
        </>
      )}
      <NumberField
        label="Client timeout" unit="ms" help="Users give up after this long; slower responses count as timeouts."
        value={p.clientTimeoutMs} onChange={(v) => set({ ...p, clientTimeoutMs: v })} error={err('clientTimeoutMs')}
      />
    </>
  )
}
