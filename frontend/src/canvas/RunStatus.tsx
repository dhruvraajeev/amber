import { useStore } from '../store'

const STATE = {
  idle: { text: 'Ready to run', dot: 'bg-faint text-faint', pulse: false },
  running: { text: 'Simulating…', dot: 'bg-accent text-accent', pulse: true },
  done: { text: 'Run complete', dot: 'bg-ok text-ok', pulse: false },
  error: { text: 'Needs attention', dot: 'bg-crit text-crit', pulse: false },
}

// Top-left of the canvas: what the simulator is doing, and the size of the design. The words carry
// the state; the dot only echoes it.
export default function RunStatus({ nodes, edges }: { nodes: number; edges: number }) {
  const status = useStore((s) => s.status)
  const seed = useStore((s) => s.result?.config.seed)
  const s = STATE[status]
  return (
    <div className="pointer-events-none absolute top-4 left-5 z-10 flex items-center gap-3 text-xs" role="status">
      <span className="flex items-center gap-2 rounded-full border border-border bg-panel/80 px-3 py-1.5 backdrop-blur-sm">
        <span className={`size-1.5 rounded-full ${s.dot} ${s.pulse ? 'pulse-dot' : ''}`} aria-hidden />
        {s.text}
        {status === 'done' && seed !== undefined && <span className="num text-muted">seed {seed}</span>}
      </span>
      <span className="num text-muted">
        {nodes} nodes · {edges} edges
      </span>
    </div>
  )
}
