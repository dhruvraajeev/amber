import type { StateCreator } from 'zustand'
import type { Store } from '.'

export type DashboardTab = 'summary' | 'latency' | 'load' | 'gpu' | 'cost' | 'bottlenecks' | 'attribution'

// Dashboard drawer state (§11.4). Not saved: a fresh page opens with the defaults.
export interface UiSlice {
  drawerOpen: boolean
  drawerHeight: number // px
  tab: DashboardTab
  setDrawer: (patch: { open?: boolean; height?: number }) => void
  setTab: (tab: DashboardTab) => void
}

export const uiSlice: StateCreator<Store, [], [], UiSlice> = (set) => ({
  drawerOpen: true,
  drawerHeight: 256,
  tab: 'summary',
  setDrawer: ({ open, height }) =>
    set((s) => ({ drawerOpen: open ?? s.drawerOpen, drawerHeight: height ?? s.drawerHeight })),
  setTab: (tab) => set({ tab }),
})
