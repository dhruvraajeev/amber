import type { StateCreator } from 'zustand'
import { ApiError, simulate } from '../api/api'
import { validate } from '../lib/validate'
import type { RunConfig, RunResult, ValidationIssue } from '../api/api'
import type { Store } from '.'

export type RunStatus = 'idle' | 'running' | 'done' | 'error'

// The latest run and its playback (§11.4). `issues` holds why the last run was refused.
export interface RunSlice {
  status: RunStatus
  result: RunResult | null
  issues: ValidationIssue[]
  pinned: RunResult[] // the two most recent pins, oldest first (Compare)
  playhead: number // index into result.timeline; the canvas shows this moment
  playing: boolean
  run: (config: RunConfig) => Promise<void>
  pin: () => void
  setPlayhead: (i: number) => void // clamped to the timeline
  togglePlay: () => void // play from the start again once at the end
}

export const runSlice: StateCreator<Store, [], [], RunSlice> = (set, get) => ({
  status: 'idle',
  result: null,
  issues: [],
  pinned: [],
  playhead: 0,
  playing: false,

  run: async (config) => {
    const { design, status } = get()
    // A second click while running is ignored, so one run is in flight at a time.
    if (!design || status === 'running') return
    const issues = validate(design, config)
    if (issues.length) return set({ status: 'error', issues })
    set({ status: 'running', issues: [], playing: false })
    try {
      set({ status: 'done', result: await simulate(design, config), playhead: 0 })
    } catch (e) {
      // The backend's refusal (its 422 issues, or why it said no) is shown and highlighted like our own.
      set({ status: 'error', issues: e instanceof ApiError ? e.issues : [] })
    }
  },
  pin: () => {
    const { result, pinned } = get()
    if (result && !pinned.includes(result)) set({ pinned: [...pinned, result].slice(-2) })
  },
  setPlayhead: (i) => set((s) => ({ playhead: Math.max(0, Math.min(i, lastPoint(s.result))) })),
  togglePlay: () =>
    set((s) => {
      if (s.playing || !s.result) return { playing: false }
      return { playing: true, playhead: s.playhead >= lastPoint(s.result) ? 0 : s.playhead }
    }),
})

export const lastPoint = (result: RunResult | null) => Math.max(0, (result?.timeline.length ?? 0) - 1)
