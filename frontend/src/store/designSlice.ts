import type { StateCreator } from 'zustand'
import { newNode, type NodeData } from '../canvas/map'
import { load } from '../lib/storage'
import type { Design, DesignNode, NodeKind } from '../api/api'
import type { Store } from '.'

export const AUTOSAVE_KEY = 'amber.design'

// The design being edited (§11.4). `design` is null until a template or blank canvas is picked.
// `selectedId` is one node or edge id; the canvas has single selection.
export interface DesignSlice {
  design: Design | null
  selectedId: string | null
  loads: number // bumped by loadTemplate so the canvas remounts and re-fits the view
  loadTemplate: (design: Design) => void
  setName: (name: string) => void
  addNode: (kind: NodeKind, position: { x: number; y: number }) => void
  updateNode: (id: string, patch: Partial<NodeData>) => void
  moveNode: (id: string, position: { x: number; y: number }) => void
  connect: (source: string, target: string) => void
  remove: (ids: string[]) => void
  select: (id: string | null) => void
}

// Every edit replaces `design`, so the autosave subscription in index.ts sees each one.
export const designSlice: StateCreator<Store, [], [], DesignSlice> = (set, get) => {
  const edit = (fn: (d: Design) => Partial<Design>) => {
    const d = get().design
    if (d) set({ design: { ...d, ...fn(d) } })
  }
  const mapNodes = (id: string, fn: (n: DesignNode) => DesignNode) =>
    edit((d) => ({ nodes: d.nodes.map((n) => (n.id === id ? fn(n) : n)) }))

  return {
    design: restore(),
    selectedId: null,
    loads: 0,

    // A new design starts with no result: the last run belongs to the old one (pins are kept for Compare).
    loadTemplate: (design) =>
      set((s) => ({
        design: structuredClone(design), selectedId: null, loads: s.loads + 1, home: false,
        status: 'idle', result: null, issues: [], playhead: 0, playing: false,
      })),
    setName: (name) => edit(() => ({ name })),

    addNode: (kind, position) => {
      const d = get().design
      if (!d) return
      const node = newNode(kind, position, new Set(d.nodes.map((n) => n.id)))
      set({ design: { ...d, nodes: [...d.nodes, node] }, selectedId: node.id })
    },
    updateNode: (id, patch) => mapNodes(id, (n) => ({ ...n, ...patch }) as DesignNode),
    moveNode: (id, position) => mapNodes(id, (n) => ({ ...n, position })),

    // Edges leaving an agent carry a role (§7.1): "llm" when they point at an LLM, otherwise "tool".
    // Whether the result is legal (e.g. exactly one llm edge) is the validator's job.
    connect: (source, target) =>
      edit((d) => {
        if (source === target || d.edges.some((e) => e.source === source && e.target === target)) return {}
        const kind = (id: string) => d.nodes.find((n) => n.id === id)?.kind
        const edge = { id: `e_${source}_${target}`, source, target }
        return { edges: [...d.edges, kind(source) === 'agent' ? { ...edge, role: kind(target) === 'llm' ? 'llm' : 'tool' } : edge] }
      }),

    // Removing a node also removes every edge touching it.
    remove: (ids) => {
      const gone = new Set(ids)
      edit((d) => ({
        nodes: d.nodes.filter((n) => !gone.has(n.id)),
        edges: d.edges.filter((e) => !gone.has(e.id) && !gone.has(e.source) && !gone.has(e.target)),
      }))
      const { selectedId } = get()
      if (selectedId && gone.has(selectedId)) set({ selectedId: null })
    },
    select: (selectedId) => set({ selectedId }),
  }
}

// The autosaved design, if it still looks like one. Anything else (old format, hand-edited) is dropped.
function restore(): Design | null {
  const d = load(AUTOSAVE_KEY) as Design | null
  return d?.version === 1 && Array.isArray(d.nodes) && Array.isArray(d.edges) ? d : null
}
