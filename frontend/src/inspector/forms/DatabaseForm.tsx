import databases from '@shared/presets/databases.json'
import type { DatabaseParams } from '../../types/contracts'
import { DistField, NumberField, SelectField, type FormProps } from '../fields'

const PRESETS = [
  { value: 'postgres', label: 'Postgres' },
  { value: 'mongodb', label: 'MongoDB' },
  { value: 'vector', label: 'Vector database' },
  { value: 'custom', label: 'Custom' },
] as const

export default function DatabaseForm({ params: p, set, err }: FormProps<DatabaseParams>) {
  return (
    <>
      <SelectField
        label="Type" help="Picking a type fills typical pool size, query time and price; Custom keeps your numbers."
        value={p.preset} options={[...PRESETS]}
        onChange={(preset) => {
          const d = databases.find((x) => x.preset === preset)
          set(d ? { preset, connectionPool: d.connectionPool, queueLimit: d.queueLimit, query: d.query, costPerMonth: d.costPerMonth } : { ...p, preset })
        }}
      />
      <NumberField
        label="Connection pool" help="Queries the database runs at once; more wait in line." step={1}
        value={p.connectionPool} onChange={(connectionPool) => set({ ...p, connectionPool })} error={err('connectionPool')}
      />
      <NumberField
        label="Queue limit" help="Queries that can wait for a connection before new ones are rejected." step={1}
        value={p.queueLimit} onChange={(queueLimit) => set({ ...p, queueLimit })} error={err('queueLimit')}
      />
      <DistField
        label="Query time" help="Time one query takes once it has a connection."
        value={p.query} onChange={(query) => set({ ...p, query })} error={err('query')}
      />
      <NumberField
        label="Cost" unit="USD/mo" help="Monthly price of the database."
        value={p.costPerMonth} onChange={(costPerMonth) => set({ ...p, costPerMonth })} error={err('costPerMonth')}
      />
    </>
  )
}
