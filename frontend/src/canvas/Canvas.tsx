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
import { useRef, useState, type DragEvent } from 'react'
import type { Design, NodeKind } from '../types/contracts'
import { newNode, toFlow, type FlowEdge, type FlowNode } from './map'
import NodeCard from './nodes/NodeCard'
import Palette, { DRAG_MIME } from './Palette'

const nodeTypes = Object.fromEntries(
  (['users', 'loadBalancer', 'service', 'cache', 'database', 'agent', 'llm'] satisfies NodeKind[]).map((k) => [k, NodeCard]),
)

const GRID = 20

// Renders two layout cells: the palette column and the React Flow pane.
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

  const add = (kind: NodeKind, screen?: { x: number; y: number }) => {
    if (!screen) {
      // Palette click: middle of the pane, nudged per node so repeated clicks don't stack exactly.
      const r = pane.current!.getBoundingClientRect()
      const nudge = (nodes.length % 5) * 24
      screen = { x: r.left + r.width / 2 - 70 + nudge, y: r.top + r.height / 2 - 25 + nudge }
    }
    const node = { ...newNode(kind, screenToFlowPosition(screen, { snapToGrid: true }), new Set(nodes.map((n) => n.id))), selected: true } // added grid snap
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
          nodes={nodes}
          edges={edges}
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
    </>
  )
}
