import {
  addEdge,
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo, useRef, useState, type DragEvent } from 'react'
import type { Design, NodeKind } from '../types/contracts'
import Inspector from '../inspector/Inspector'
import { validate } from '../lib/validate'
import { newNode, toDesign, toFlow, type FlowEdge, type FlowNode, type NodeData } from './map'
import NodeCard from './nodes/NodeCard'
import Palette, { DRAG_MIME } from './Palette'

const nodeTypes = Object.fromEntries(
  (['users', 'loadBalancer', 'service', 'cache', 'database', 'agent', 'llm'] satisfies NodeKind[]).map((k) => [k, NodeCard]),
)

const GRID = 20

// Renders three layout cells: the palette column, the React Flow pane, and the inspector.
// Holds the graph locally for now; Step 6 moves it into the Zustand design slice.
export default function Canvas({ design }: { design: Design }) {
  return (
    <ReactFlowProvider>
      <Flow design={design} />
    </ReactFlowProvider>
  )
}

function Flow({ design }: { design: Design }) {
  const [initial] = useState(() => toFlow(design))
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(initial.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>(initial.edges)
  const { screenToFlowPosition } = useReactFlow()
  const pane = useRef<HTMLDivElement>(null)

  // Re-checked on every edit; ≤50 nodes keeps this cheap. Flagged nodes and edges get an `invalid` class.
  const issues = useMemo(() => validate(toDesign(design, nodes, edges)), [design, nodes, edges])
  const flagged = new Set(issues.flatMap((i) => [i.nodeId, i.edgeId]))
  const mark = <T extends { id: string }>(xs: T[]) => xs.map((x) => (flagged.has(x.id) ? { ...x, className: 'invalid' } : x))
  const selected = nodes.filter((n) => n.selected)
  const update = (id: string, data: NodeData) => setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data } : n)))

  const add = (kind: NodeKind, screen?: { x: number; y: number }) => {
    let position
    if (screen) {
      // Dropped from the palette: wherever the mouse let go.
      position = screenToFlowPosition(screen, { snapToGrid: true })
    } else if (nodes.length > 0) {
      // Clicked in the palette: to the right of the rightmost node, so clicks build a chain.
      const last = nodes.reduce((a, b) => (b.position.x > a.position.x ? b : a))
      position = { x: last.position.x + 220, y: last.position.y }
    } else {
      // First node on an empty canvas: the middle of the pane.
      const r = pane.current!.getBoundingClientRect()
      position = screenToFlowPosition({ x: r.left + r.width / 2, y: r.top + r.height / 2 }, { snapToGrid: true })
    }
    const node = { ...newNode(kind, position, new Set(nodes.map((n) => n.id))), selected: true }
    setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), node])
  }

  const onDrop = (e: DragEvent) => {
    const kind = e.dataTransfer.getData(DRAG_MIME) as NodeKind
    if (!kind) return
    e.preventDefault()
    add(kind, { x: e.clientX, y: e.clientY })
  }

  // Edges leaving an agent carry a role (§7.1): "llm" when they point at an LLM, otherwise "tool".
  // Whether the result is legal (e.g. exactly one llm edge) is Step 5's validator's job.
  const onConnect = (c: Connection) => {
    const kindOf = (id: string) => nodes.find((n) => n.id === id)?.data.kind
    const role = kindOf(c.source) === 'agent' ? (kindOf(c.target) === 'llm' ? 'llm' : 'tool') : undefined
    const edge: FlowEdge = { ...c, id: `e_${c.source}_${c.target}`, data: { role }, label: role }
    setEdges((es) => addEdge(edge, es))
  }

  return (
    <>
      <Palette onAdd={add} />
      <main
        ref={pane}
        className="min-h-0 bg-bg"
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        onKeyDown={(e) => {
          if (e.key !== 'Escape') return
          setNodes((ns) => ns.map((n) => ({ ...n, selected: false })))
          setEdges((es) => es.map((ed) => ({ ...ed, selected: false })))
        }}
      >
        <ReactFlow
          nodes={mark(nodes)}
          edges={mark(edges)}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          isValidConnection={(c) => c.source !== c.target}
          deleteKeyCode={['Delete', 'Backspace']}
          snapToGrid
          snapGrid={[GRID, GRID]}
          colorMode="dark"
          fitView
        >
          <Background variant={BackgroundVariant.Dots} gap={GRID} size={1.5} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </main>
      <Inspector node={selected.length === 1 ? selected[0] : undefined} issues={issues} onChange={update} />
    </>
  )
}
