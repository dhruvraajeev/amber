import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import { lastPoint } from '../store/runSlice'
import type { DesignEdge, RunResult, TimelinePoint } from '../api/api'

// Timeline playback (§11.3). The run slice holds `playhead` and `playing`; this file moves the
// playhead forward and gives the canvas what each node and edge looks like at that moment.

const TICK_MS = 100 // one timeline point per 100 ms

/** While playing, advances one point per tick and stops at the end. Mount once (the run bar does). */
export function usePlaybackClock() {
  const playing = useStore((s) => s.playing)
  useEffect(() => {
    if (!playing) return
    const id = setInterval(() => {
      const { result, playhead, setPlayhead, togglePlay } = useStore.getState()
      if (playhead >= lastPoint(result)) togglePlay()
      else setPlayhead(playhead + 1)
    }, TICK_MS)
    return () => clearInterval(id)
  }, [playing])
}

/** A node's load at the playhead, or undefined before a run (or if the node was added since). */
export const useNodeLoad = (id: string): TimelinePoint['nodes'][string] | undefined =>
  useStore((s) => s.result?.timeline[s.playhead]?.nodes[id])

/** Traffic along the edges into `target` at the playhead, plus the run's busiest edge rate for scaling. */
export function useEdgeTraffic(target: string) {
  return useStore(
    useShallow((s) => {
      const now = s.result?.timeline[s.playhead]?.nodes[target]
      if (!now || !s.design) return undefined
      return { rps: now.throughputRps / fanIn(s.design.edges, target), peak: peakEdgeRps(s.result!, s.design.edges), errors: now.rejects > 0 }
    }),
  )
}

// ponytail: the timeline has per-node, not per-edge, rates → an edge carries its target's throughput,
// split evenly across the target's incoming edges. Exact per-edge counts come with the real simulator.
const fanIn = (edges: DesignEdge[], target: string) => edges.filter((e) => e.target === target).length

const peaks = new WeakMap<RunResult, number>()
/** Highest per-edge rate anywhere in the run, computed once per result. */
function peakEdgeRps(result: RunResult, edges: DesignEdge[]): number {
  let peak = peaks.get(result)
  if (peak === undefined) {
    const targets = new Set(edges.map((e) => e.target))
    peak = 0
    for (const p of result.timeline)
      for (const [id, n] of Object.entries(p.nodes)) if (targets.has(id)) peak = Math.max(peak, n.throughputRps / fanIn(edges, id))
    peaks.set(result, peak)
  }
  return peak
}
