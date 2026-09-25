import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type EdgeChange,
  type NodeChange,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo, useRef, useState, type DragEvent } from 'react'
import { useShallow } from 'zustand/react/shallow'
import Inspector from '../inspector/Inspector'
import { validate } from '../lib/validate'
import { useStore } from '../store'
import type { NodeKind } from '../api/api'
import CostTicker from './CostTicker'
import PlaybackBar from '../run/PlaybackBar'
import RunStatus from './RunStatus'
import TrafficEdge from './edges/TrafficEdge'
import { toFlowEdge, toFlowNode, type FlowEdge, type FlowNode } from './map'
import NodeCard from './nodes/NodeCard'
import Palette, { DRAG_MIME } from './Palette'

const nodeTypes = Object.fromEntries(
  (['users', 'loadBalancer', 'service', 'cache', 'database', 'agent', 'llm'] satisfies NodeKind[]).map((k) => [k, NodeCard]),
)

const edgeTypes = { traffic: TrafficEdge }

const GRID = 20
const EXIT_MS = 180 // the ember exit (theme.css .ember-out) plays before a deleted node goes

// Renders three layout cells: the palette column, the React Flow pane, and the inspector.
// The design lives in the store; React Flow only draws it and reports edits back.
export default function Canvas() {
  return (
    <ReactFlowProvider>
      <Flow />
    </ReactFlowProvider>
  )
}

type Size = { width: number; height: number }

function Flow() {
  const { design, selectedId, addNode, updateNode, moveNode, connect, remove, select } = useStore(
    useShallow(({ design, selectedId, addNode, updateNode, moveNode, connect, remove, select }) =>
      ({ design: design!, selectedId, addNode, updateNode, moveNode, connect, remove, select })),
  )
  const { screenToFlowPosition } = useReactFlow()
  const pane = useRef<HTMLDivElement>(null)
  // React Flow measures each node after it renders and needs that size handed back on every render,
  // or it hides the node. Sizes are view state, so they stay here rather than in the design.
  const [sizes, setSizes] = useState<Record<string, Size>>({})
  // Nodes mid-effect: flaring in after being added from the palette, or burning out as they're deleted.
  const [flash, setFlash] = useState<Record<string, 'ember-in' | 'ember-out'>>({})
  const unflash = (ids: string[]) => setFlash((f) => Object.fromEntries(Object.entries(f).filter(([id]) => !ids.includes(id))))

  // Re-checked on every edit; ≤50 nodes keeps this cheap. Flagged nodes and edges get an `invalid` class,
  // as do those named by the last refused run (the backend's 422), until the next run.
  const issues = useMemo(() => validate(design), [design])
  const refused = useStore((s) => s.issues)
  const flagged = new Set([...issues, ...refused].flatMap((i) => [i.nodeId, i.edgeId]))
  const view = <T extends { id: string }>(x: T) => ({
    ...x,
    selected: x.id === selectedId,
    className: [flagged.has(x.id) && 'invalid', flash[x.id]].filter(Boolean).join(' ') || undefined,
  })
  const nodes: FlowNode[] = design.nodes.map((n) => view({ ...toFlowNode(n), measured: sizes[n.id] }))
  const edges: FlowEdge[] = design.edges.map((e) => view(toFlowEdge(e)))

  // Clicking B while A is selected reports "B selected" and "A deselected" in either order,
  // so a deselect only clears the selection if it is still the current one.
  const onSelect = (id: string, on: boolean) => {
    if (on) select(id)
    else if (useStore.getState().selectedId === id) select(null)
  }

  // Only the changes Amber cares about; React Flow's others (hover, replace) are ignored.
  const onNodesChange = (changes: NodeChange<FlowNode>[]) => {
    const removed: string[] = []
    for (const c of changes) {
      if (c.type === 'position' && c.position) moveNode(c.id, c.position)
      else if (c.type === 'dimensions' && c.dimensions) setSizes((s) => ({ ...s, [c.id]: c.dimensions! }))
      else if (c.type === 'select') onSelect(c.id, c.selected)
      else if (c.type === 'remove') removed.push(c.id)
    }
    if (removed.length) {
      remove(removed)
      unflash(removed) // an id can be reused later; it mustn't inherit a finished exit
    }
  }
  const onEdgesChange = (changes: EdgeChange<FlowEdge>[]) => {
    const removed = changes.flatMap((c) => (c.type === 'remove' ? [c.id] : []))
    if (removed.length) remove(removed)
    for (const c of changes) if (c.type === 'select') onSelect(c.id, c.selected)
  }

  const add = (kind: NodeKind, screen?: { x: number; y: number }) => {
    let position
    if (screen) {
      // Dropped from the palette: wherever the mouse let go.
      position = screenToFlowPosition(screen, { snapToGrid: true })
    } else if (design.nodes.length > 0) {
      // Clicked in the palette: to the right of the rightmost node, so clicks build a chain.
      const last = design.nodes.reduce((a, b) => (b.position.x > a.position.x ? b : a))
      position = { x: last.position.x + 220, y: last.position.y }
    } else {
      // First node on an empty canvas: the middle of the pane.
      const r = pane.current!.getBoundingClientRect()
      position = screenToFlowPosition({ x: r.left + r.width / 2, y: r.top + r.height / 2 }, { snapToGrid: true })
    }
    addNode(kind, position)
    const id = useStore.getState().selectedId! // addNode selects what it added
    setFlash((f) => ({ ...f, [id]: 'ember-in' }))
    setTimeout(() => unflash([id]), 700)
  }

  const onDrop = (e: DragEvent) => {
    const kind = e.dataTransfer.getData(DRAG_MIME) as NodeKind
    if (!kind) return
    e.preventDefault()
    add(kind, { x: e.clientX, y: e.clientY })
  }

  const node = design.nodes.find((n) => n.id === selectedId)
  return (
    <>
      <Palette onAdd={add} />
      <main
        ref={pane}
        className="panel hud-corners relative min-h-0 overflow-hidden"
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        onKeyDown={(e) => e.key === 'Escape' && select(null)}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={(c) => connect(c.source, c.target)}
          isValidConnection={(c) => c.source !== c.target}
          deleteKeyCode={['Delete', 'Backspace']}
          onBeforeDelete={async ({ nodes: gone }) => {
            if (gone.length) {
              setFlash((f) => ({ ...f, ...Object.fromEntries(gone.map((n) => [n.id, 'ember-out'] as const)) }))
              await new Promise((done) => setTimeout(done, EXIT_MS))
            }
            return true
          }}
          multiSelectionKeyCode={null}
          panActivationKeyCode={null} // Space toggles playback instead; dragging the pane still pans
          snapToGrid
          snapGrid={[GRID, GRID]}
          colorMode="dark"
          fitView
          fitViewOptions={{ padding: 0.3, maxZoom: 1.1 }}
        >
          <Background variant={BackgroundVariant.Dots} gap={GRID} size={1.2} />
          <Controls showInteractive={false} position="bottom-left" />
        </ReactFlow>
        <RunStatus nodes={design.nodes.length} edges={design.edges.length} />
        <CostTicker />
        <PlaybackBar />
      </main>
      <Inspector node={node} issues={issues} onChange={updateNode} />
    </>
  )
}
