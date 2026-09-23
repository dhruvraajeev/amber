import { BaseEdge, getBezierPath, type EdgeProps } from '@xyflow/react'
import { dotCount, dotSeconds } from '../../lib/color'
import { useEdgeTraffic } from '../../run/Playback'
import type { FlowEdge } from '../map'

// Every edge (§11.3). Before a run: a plain curve. After: thickness follows throughput at the playhead,
// amber dots travel along it (more and faster as traffic rises, at most 8), and it turns rust when its
// target is turning requests away. Under prefers-reduced-motion, theme.css hides the dots and dashes the line.
export default function TrafficEdge({ target, label, markerEnd, interactionWidth, ...geometry }: EdgeProps<FlowEdge>) {
  const [path, labelX, labelY] = getBezierPath(geometry)
  const traffic = useEdgeTraffic(target)
  if (!traffic) return <BaseEdge path={path} label={label} labelX={labelX} labelY={labelY} markerEnd={markerEnd} interactionWidth={interactionWidth} />

  const { rps, peak, errors } = traffic
  const n = dotCount(rps, peak)
  const dur = dotSeconds(rps, peak)
  return (
    <>
      <BaseEdge
        path={path} label={label} labelX={labelX} labelY={labelY} markerEnd={markerEnd} interactionWidth={interactionWidth}
        className={`traffic${errors ? ' erroring' : ''}`}
        style={{ strokeWidth: 1 + 3 * Math.min(1, rps / (peak || 1)) }}
      />
      <g className="traffic-dots" aria-hidden>
        {Array.from({ length: n }, (_, i) => (
          <circle key={i} r={3} fill={errors ? 'var(--crit)' : 'var(--accent)'}>
            {/* Negative begin offsets spread the dots evenly along the path. */}
            <animateMotion dur={`${dur}s`} begin={`${(-i * dur) / n}s`} repeatCount="indefinite" path={path} />
          </circle>
        ))}
      </g>
    </>
  )
}
