import type { CacheParams } from '../../api/api'
import { DistField, NumberField, SliderField, type FormProps } from '../fields'

export default function CacheForm({ params: p, set, err }: FormProps<CacheParams>) {
  return (
    <>
      <SliderField
        label="Hit rate" help="Share of requests answered from the cache; the rest go to the node behind it."
        value={p.hitRate} onChange={(hitRate) => set({ ...p, hitRate })} error={err('hitRate')}
      />
      <DistField
        label="Latency" help="Time for one cache lookup, hit or miss."
        value={p.latency} onChange={(latency) => set({ ...p, latency })} error={err('latency')}
      />
      <NumberField
        label="Cost" unit="USD/mo" help="Monthly price of the cache."
        value={p.costPerMonth} onChange={(costPerMonth) => set({ ...p, costPerMonth })} error={err('costPerMonth')}
      />
    </>
  )
}
