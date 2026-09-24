import { CircleCheck, TriangleAlert } from 'lucide-react'
import { KINDS, type NodeData } from '../canvas/map'
import type { DesignNode, ValidationIssue } from '../api/api'
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
  node?: DesignNode; issues: ValidationIssue[]; onChange: (id: string, patch: Partial<NodeData>) => void
}) {
  return (
    <aside className="panel flex min-h-0 flex-col gap-3.5 overflow-y-auto p-4" aria-label="Inspector">
      {node ? <NodeInspector node={node} issues={issues.filter((i) => i.nodeId === node.id)} onChange={onChange} /> : <DesignIssues issues={issues} />}
    </aside>
  )
}

function DesignIssues({ issues }: { issues: ValidationIssue[] }) {
  return (
    <>
      <h2 className="text-[15px] font-semibold">Design check</h2>
      {issues.length === 0 ? (
        <div className="flex gap-3 rounded-xl border border-border bg-panel-2 p-3.5 text-[13px] text-muted">
          <CircleCheck size={18} className="mt-px shrink-0 text-ok" aria-hidden />
          <p>
            <span className="text-text">No problems found.</span> Select a node to edit its parameters.
          </p>
        </div>
      ) : (
        <IssueList issues={issues} />
      )}
    </>
  )
}

function IssueList({ issues }: { issues: ValidationIssue[] }) {
  return (
    <ul className="flex flex-col gap-2 text-[13px]" aria-label={`${issues.length} issues`}>
      {issues.map((i, n) => (
        <li key={n} className="flex gap-2.5 rounded-xl border border-crit/40 bg-crit/[0.07] px-3 py-2.5 leading-snug">
          <TriangleAlert size={15} className="mt-0.5 shrink-0 text-warn" aria-hidden />
          {i.message}
        </li>
      ))}
    </ul>
  )
}

function NodeInspector({ node: d, issues, onChange }: { node: DesignNode; issues: ValidationIssue[]; onChange: (id: string, patch: Partial<NodeData>) => void }) {
  // Inline messages drop the "Label: " prefix the validator adds for the design-wide list.
  const prefix = `${d.label}: `
  const short = (m: string) => (m.startsWith(prefix) ? m.slice(prefix.length) : m)
  const byPath = new Map(issues.filter((i) => i.path).map((i) => [i.path!.replace(/^params\./, ''), short(i.message)]))
  const err: Errors = (path) => byPath.get(path)
  const graphIssues = issues.filter((i) => !i.path)
  const { name, icon: Icon } = KINDS.find((k) => k.kind === d.kind)!

  return (
    <>
      <h2 className="flex items-center gap-3 border-b border-border pb-3.5">
        <span className="grid size-9 place-items-center rounded-[0.7rem] border border-accent/25 bg-accent/10 text-accent shadow-[0_6px_18px_-8px_rgb(255_106_43/0.7)]">
          <Icon size={17} strokeWidth={1.75} aria-hidden />
        </span>
        <span className="flex flex-col">
          <span className="text-[15px] font-semibold leading-tight">{name}</span>
          <span className="num text-[11px] text-muted">{d.id}</span>
        </span>
      </h2>
      {graphIssues.length > 0 && <IssueList issues={graphIssues} />}
      <TextField label="Label" help="The name shown on the canvas and in results." value={d.label} onChange={(label) => onChange(d.id, { label })} />
      <Form data={d} set={(data) => onChange(d.id, data)} err={err} />
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
