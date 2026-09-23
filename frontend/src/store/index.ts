import { create } from 'zustand'
import { save } from '../lib/storage'
import { AUTOSAVE_KEY, designSlice, type DesignSlice } from './designSlice'
import { runSlice, type RunSlice } from './runSlice'
import { uiSlice, type UiSlice } from './uiSlice'

// One Zustand store built from three slices (§11.4). Components read it with
// `useStore((s) => s.field)` so they re-render only when that field changes.
export type Store = DesignSlice & RunSlice & UiSlice

export const useStore = create<Store>()((...a) => ({ ...designSlice(...a), ...runSlice(...a), ...uiSlice(...a) }))

// Autosave: every design edit is written to localStorage (a no-op when storage is blocked).
useStore.subscribe((s, prev) => {
  if (s.design !== prev.design) save(AUTOSAVE_KEY, s.design)
})
