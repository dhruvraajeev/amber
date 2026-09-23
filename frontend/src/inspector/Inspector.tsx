import { KINDS, type FlowNode, type NodeData } from '../canvas/map'
import type { ValidationIssue } from '../types/contracts'
import { TextField, type Errors } from './fields'
import AgentForm from './forms/AgentForm'
import CacheForm from './forms/CacheForm'
import DatabaseForm from './forms/DatabaseForm'
import LlmForm from './forms/LlmForm'
import LoadBalancerForm from './forms/LoadBalancerForm'
import ServiceForm from './forms/ServiceForm'
import UsersForm from './forms/UsersForm'

// Right-hand panel (§11.2). With one node selected: its label and parameter form, with the
// validator's messages inline. Otherwise: every issue in the design, so nothing hides.
export default function Inspector({ node, issues, onChange }: {
  node?: FlowNode; issues: ValidationIssue[]; onChange: (id: string, data: NodeData) => void
}) {
  return (
    <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto border-l border-border bg-panel p-3" aria-label="Inspector">
      {node ? <NodeInspector node={node} issues={issues.filter((i) => i.nodeId === node.id)} onChange={onChange} /> : <DesignIssues issues={issues} />}
    </aside>
  )
}

function DesignIssues({ issues }: { issues: ValidationIssue[] }) {
  return (
    <>
      <h2 className="text-sm font-semibold">Design check</h2>
      {issues.length === 0 ? (
        <p className="text-sm text-muted">✓ No problems found. Select a node to edit its parameters.</p>
      ) : (
        <IssueList issues={issues} />
      )}
    </>
  )
}

function IssueList({ issues }: { issues: ValidationIssue[] }) {
  return (
    <ul className="flex flex-col gap-2 text-sm" aria-label={`${issues.length} issues`}>
      {issues.map((i, n) => (
        <li key={n} className="rounded border border-crit bg-panel-2 px-2 py-1.5">
          <span className="text-warn">⚠</span> {i.message}
        </li>
      ))}
    </ul>
  )
}

function NodeInspector({ node, issues, onChange }: { node: FlowNode; issues: ValidationIssue[]; onChange: (id: string, data: NodeData) => void }) {
  const d = node.data
  // Inline messages drop the "Label: " prefix the validator adds for the design-wide list.
  const prefix = `${d.label}: `
  const short = (m: string) => (m.startsWith(prefix) ? m.slice(prefix.length) : m)
  const byPath = new Map(issues.filter((i) => i.path).map((i) => [i.path!.replace(/^params\./, ''), short(i.message)]))
  const err: Errors = (path) => byPath.get(path)
  const graphIssues = issues.filter((i) => !i.path)
  const { name, icon } = KINDS.find((k) => k.kind === d.kind)!

  return (
    <>
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <span className="text-accent" aria-hidden>{icon}</span>
        {name}
      </h2>
      {graphIssues.length > 0 && <IssueList issues={graphIssues} />}
      <TextField label="Label" help="The name shown on the canvas and in results." value={d.label} onChange={(label) => onChange(node.id, { ...d, label })} />
      <Form data={d} set={(data) => onChange(node.id, data)} err={err} />
    </>
  )
}

// One form per kind; the `kind` check narrows `params` for each.
function Form({ data: d, set, err }: { data: NodeData; set: (d: NodeData) => void; err: Errors }) {
  switch (d.kind) {
    case 'users': return <UsersForm params={d.params} set={(params) => set({ ...d, params })} err={err} />
    case 'loadBalancer': return <LoadBalancerForm params={d.params} set={(params) => set({ ...d, params })} err={err} />
    case 'service': return <ServiceForm params={d.params} set={(params) => set({ ...d, params })} err={err} />
    case 'cache': return <CacheForm params={d.params} set={(params) => set({ ...d, params })} err={err} />
    case 'database': return <DatabaseForm params={d.params} set={(params) => set({ ...d, params })} err={err} />
    case 'agent': return <AgentForm params={d.params} set={(params) => set({ ...d, params })} err={err} />
    case 'llm': return <LlmForm params={d.params} set={(params) => set({ ...d, params })} err={err} />
  }
}
