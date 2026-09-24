import type { LoadBalancerParams } from '../../api/api'
import { DistField, SelectField, type FormProps } from '../fields'

export default function LoadBalancerForm({ params: p, set, err }: FormProps<LoadBalancerParams>) {
  return (
    <>
      <SelectField
        label="Algorithm" help="Round robin takes turns; least connections picks the target with the fewest requests in flight."
        value={p.algorithm}
        options={[{ value: 'roundRobin', label: 'Round robin' }, { value: 'leastConnections', label: 'Least connections' }]}
        onChange={(algorithm) => set({ ...p, algorithm })}
      />
      <DistField
        label="Overhead" help="Time the load balancer itself adds to each request."
        value={p.overhead} onChange={(overhead) => set({ ...p, overhead })} error={err('overhead')}
      />
    </>
  )
}
