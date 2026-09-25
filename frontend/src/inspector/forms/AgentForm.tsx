import { agentPerRequest } from '../../lib/ai'
import { count } from '../../lib/format'
import type { AgentParams } from '../../api/api'
import { DistField, NumberField, Readout, type FormProps } from '../fields'

type NumKey = Exclude<keyof AgentParams, 'toolLatency'>

export default function AgentForm({ params: p, set, err }: FormProps<AgentParams>) {
  const num = (key: NumKey, label: string, help: string, unit?: string, step?: number) => (
    <NumberField label={label} unit={unit} help={help} value={p[key]} onChange={(v) => set({ ...p, [key]: v })} error={err(key)} step={step} />
  )
  return (
    <>
      {num('llmCallsMean', 'LLM calls per request', 'Average number of LLM calls the agent makes per request (at least 1).')}
      {num('toolCallsPerStep', 'Tool calls per step', 'Tool calls the agent makes between two LLM calls.', undefined, 1)}
      <DistField
        label="Tool latency" help="How long one tool call takes. Used only when the agent has no tool edges."
        value={p.toolLatency} onChange={(toolLatency) => set({ ...p, toolLatency })} error={err('toolLatency')}
      />
      {num('basePromptTokens', 'Base prompt', 'Prompt size of the first LLM call.', 'tokens', 1)}
      {num('contextGrowthTokensPerStep', 'Context growth per step', 'Tokens each later LLM call adds to the prompt, as history piles up.', 'tokens', 1)}
      {num('outputTokensPerCall', 'Output per call', 'Tokens the LLM writes on each call.', 'tokens', 1)}
      <PerRequest params={p} />
    </>
  )
}

/** The average request these numbers add up to; hidden while a field is empty or out of range. */
function PerRequest({ params }: { params: AgentParams }) {
  const r = agentPerRequest(params)
  if (params.llmCallsMean < 1 || !Object.values(r).every(Number.isFinite)) return null
  // Averages can be fractional (2.5 LLM calls), so keep one decimal rather than round to a whole call.
  const calls = (n: number, what: string) => `${n.toLocaleString('en-US', { maximumFractionDigits: 1 })} ${what}${n === 1 ? '' : 's'}`
  return (
    <Readout>
      On average a request makes {calls(r.llmCalls, 'LLM call')} and {calls(r.toolCalls, 'tool call')}, sending{' '}
      {count(r.promptTokens)} prompt tokens in all and getting {count(r.outputTokens)} back.
    </Readout>
  )
}
