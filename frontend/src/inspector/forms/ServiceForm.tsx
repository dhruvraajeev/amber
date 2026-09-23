import services from '@shared/presets/services.json'
import type { ServiceParams } from '../../types/contracts'
import { DistField, NumberField, SelectField, type FormProps } from '../fields'

export default function ServiceForm({ params: p, set, err }: FormProps<ServiceParams>) {
  const num = (key: 'replicas' | 'concurrencyPerReplica' | 'queueLimit' | 'costPerReplicaMonth', label: string, help: string, unit?: string) => (
    <NumberField label={label} unit={unit} help={help} value={p[key]} onChange={(v) => set({ ...p, [key]: v })} error={err(key)} step={1} />
  )
  return (
    <>
      <SelectField
        label="Size preset" help="Fills concurrency, queue, work time and price from a typical container size; replicas stay as they are."
        value="" placeholder="Fill from preset…" options={services.map((s) => ({ value: s.id, label: s.name }))}
        onChange={(id) => {
          const { concurrencyPerReplica, queueLimit, work, costPerReplicaMonth } = services.find((s) => s.id === id)!
          set({ ...p, concurrencyPerReplica, queueLimit, work, costPerReplicaMonth })
        }}
      />
      {num('replicas', 'Replicas', 'How many copies of this service run side by side (1–50).')}
      {num('concurrencyPerReplica', 'Concurrency per replica', 'Requests one replica works on at once, like its thread or worker count.')}
      {num('queueLimit', 'Queue limit', 'Requests that can wait per replica before new ones are rejected with a 503.')}
      <DistField
        label="Work time" help="The service's own processing time per request, not counting calls it makes downstream."
        value={p.work} onChange={(work) => set({ ...p, work })} error={err('work')}
      />
      {num('costPerReplicaMonth', 'Cost per replica', 'Monthly price of one replica.', 'USD/mo')}
    </>
  )
}
