import type { StateCreator } from 'zustand'
import { simulate } from '../api/api'
import { validate } from '../lib/validate'
import type { RunConfig, RunResult, ValidationIssue } from '../types/contracts'
import type { Store } from '.'

export type RunStatus = 'idle' | 'running' | 'done' | 'error'

// The latest run and its playback (§11.4). `issues` holds why the last run was refused.
export interface RunSlice {
  status: RunStatus
  result: RunResult | null
  issues: ValidationIssue[]
  pinned: RunResult[] // the two most recent pins, oldest first (Compare, Step 8)
  playhead: number // index into result.timeline
  playing: boolean
  run: (config: RunConfig) => Promise<void>
  pin: () => void
  setPlayhead: (i: number) => void
  setPlaying: (playing: boolean) => void
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
    } catch {
      set({ status: 'error' })
    }
  },
  pin: () => {
    const { result, pinned } = get()
    if (result && !pinned.includes(result)) set({ pinned: [...pinned, result].slice(-2) })
  },
  setPlayhead: (playhead) => set({ playhead }),
  setPlaying: (playing) => set({ playing }),
})
