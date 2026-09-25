import gpus from '@shared/presets/gpus.json'
import hostedLlms from '@shared/presets/hosted_llms.json'
import models from '@shared/presets/models.json'
import { LLM_DEFAULTS } from '../../canvas/map'
import { kvBudget } from '../../lib/ai'
import { count } from '../../lib/format'
import type { HostedLlmParams, LlmParams, SelfHostedLlmParams } from '../../api/api'
import { DistField, NumberField, Readout, SelectField, SliderField, ToggleField, type FormProps } from '../fields'

// ponytail: the backend's one timing profile (sim/nodes/llm_selfhosted.py PROFILES). Calibration (v1.1) measures real
// ones into shared/profiles/, and this list should then be read from there.
const PROFILES = [{ value: 'default', label: 'Default (uncalibrated)' }]

// The form swaps entirely on `mode`: hosted APIs and self-hosted GPUs share no fields.
export default function LlmForm({ params: p, set, err }: FormProps<LlmParams>) {
  return (
    <>
      <SelectField
        label="Mode" help="Hosted calls a provider's API; self-hosted runs the model on GPUs you pay for by the hour."
        value={p.mode}
        options={[{ value: 'hosted', label: 'Hosted API' }, { value: 'selfHosted', label: 'Self-hosted GPU' }]}
        onChange={(mode) => mode !== p.mode && set(structuredClone(LLM_DEFAULTS[mode]))}
      />
      {p.mode === 'hosted' ? <Hosted params={p} set={set} err={err} /> : <SelfHosted params={p} set={set} err={err} />}
    </>
  )
}

function Hosted({ params: p, set, err }: FormProps<HostedLlmParams>) {
  const tps = p.tokensPerSecond
  return (
    <>
      <SelectField
        label="Model preset" help="Fills latency, speed, prices and rate limit from a provider preset."
        value={p.presetId} options={hostedLlms.map((m) => ({ value: m.id, label: m.name }))} error={err('presetId')}
        onChange={(presetId) => {
          const { ttft, tokensPerSecond, inputUsdPer1M, outputUsdPer1M, rateLimitRpm } = hostedLlms.find((m) => m.id === presetId)!
          set({ ...p, presetId, ttft, tokensPerSecond, inputUsdPer1M, outputUsdPer1M, rateLimitRpm })
        }}
      />
      <DistField
        label="Time to first token" help="Wait before the first output token arrives."
        value={p.ttft} onChange={(ttft) => set({ ...p, ttft })} error={err('ttft')}
      />
      <div className="grid grid-cols-2 gap-2">
        <NumberField
          label="Speed p50" unit="tok/s" help="Typical output speed."
          value={tps.p50} onChange={(p50) => set({ ...p, tokensPerSecond: { ...tps, p50 } })} error={err('tokensPerSecond')}
        />
        <NumberField
          label="Speed slow 1%" unit="tok/s" help="Output speed on the slowest 1% of calls."
          value={tps.p99Low} onChange={(p99Low) => set({ ...p, tokensPerSecond: { ...tps, p99Low } })}
        />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <NumberField
          label="Input price" unit="USD/1M" help="Price per million prompt tokens."
          value={p.inputUsdPer1M} onChange={(inputUsdPer1M) => set({ ...p, inputUsdPer1M })} error={err('inputUsdPer1M')}
        />
        <NumberField
          label="Output price" unit="USD/1M" help="Price per million output tokens."
          value={p.outputUsdPer1M} onChange={(outputUsdPer1M) => set({ ...p, outputUsdPer1M })} error={err('outputUsdPer1M')}
        />
      </div>
      <NumberField
        label="Rate limit" unit="req/min" help="Requests per minute the provider allows before answering 429." step={1}
        value={p.rateLimitRpm} onChange={(rateLimitRpm) => set({ ...p, rateLimitRpm })} error={err('rateLimitRpm')}
      />
      <NumberField
        label="Max retries" help="How many times a rate-limited call is retried, with backoff, before it fails." step={1}
        value={p.maxRetries} onChange={(maxRetries) => set({ ...p, maxRetries })} error={err('maxRetries')}
      />
    </>
  )
}

function SelfHosted({ params: p, set, err }: FormProps<SelfHostedLlmParams>) {
  const s = p.speculative
  const num = (key: 'replicas' | 'maxBatchSize' | 'maxBatchTokens' | 'maxOutputTokensReserve', label: string, help: string, unit?: string) => (
    <NumberField label={label} unit={unit} help={help} value={p[key]} onChange={(v) => set({ ...p, [key]: v })} error={err(key)} step={1} />
  )
  const spec = (key: 'draftTokens' | 'draftStepMs', label: string, help: string, unit?: string) => (
    <NumberField
      label={label} unit={unit} help={help} value={s[key]}
      onChange={(v) => set({ ...p, speculative: { ...s, [key]: v } })} error={err(`speculative.${key}`)}
    />
  )
  const kv = kvBudget(p.gpuPresetId, p.modelPresetId)
  // An unknown profile (say, from an imported design) stays visible so the backend's error makes sense.
  const profiles = PROFILES.some((o) => o.value === p.profileId) ? PROFILES : [...PROFILES, { value: p.profileId, label: p.profileId }]
  return (
    <>
      <SelectField
        label="GPU" help="The GPU each replica runs on; its memory bounds the KV cache." value={p.gpuPresetId}
        options={gpus.map((g) => ({ value: g.id, label: `${g.name} (${g.memoryGb} GB)` }))} error={err('gpuPresetId')}
        onChange={(gpuPresetId) => set({ ...p, gpuPresetId })}
      />
      <SelectField
        label="Model" help="The model's size decides how much GPU memory is left for the KV cache." value={p.modelPresetId}
        options={models.map((m) => ({ value: m.id, label: m.name }))} error={err('modelPresetId')}
        onChange={(modelPresetId) => set({ ...p, modelPresetId })}
      />
      {kv && kv.capacityBytes > 0 && (
        <Readout>
          {(kv.capacityBytes / 1e9).toFixed(1)} GB of the {kv.gpuName} is left for the KV cache after the weights: room for{' '}
          {count(Math.floor(kv.capacityBytes / kv.bytesPerToken))} tokens at {count(kv.bytesPerToken / 1024)} KiB each. Each call
          holds its prompt plus the output reserve until it finishes.
        </Readout>
      )}
      <SelectField
        label="Timing profile" help="Measured prefill and decode speed. Only an uncalibrated default exists until calibration (v1.1) measures real hardware."
        value={p.profileId} options={profiles} error={err('profileId')}
        onChange={(profileId) => set({ ...p, profileId })}
      />
      {num('replicas', 'Replicas', 'How many GPUs serve this model, each with its own batch.')}
      {num('maxBatchSize', 'Max batch size', 'Most sequences one GPU generates at the same time.')}
      {num('maxBatchTokens', 'Max prefill', 'Prompt tokens a GPU reads in per scheduler step.', 'tokens')}
      {num('maxOutputTokensReserve', 'Output reserve', 'KV cache space set aside per request for its output.', 'tokens')}
      <ToggleField
        label="Speculative decoding" help="A small draft model guesses tokens that the big model then checks in one pass."
        value={s.enabled} onChange={(enabled) => set({ ...p, speculative: { ...s, enabled } })}
      />
      {s.enabled && (
        <>
          {spec('draftTokens', 'Draft tokens', 'Tokens the draft model guesses per step.')}
          <SliderField
            label="Acceptance rate" help="Chance the big model accepts each guessed token."
            value={s.acceptanceRate} onChange={(acceptanceRate) => set({ ...p, speculative: { ...s, acceptanceRate } })}
            error={err('speculative.acceptanceRate')}
          />
          {spec('draftStepMs', 'Draft step', 'Time the draft model takes per guessed token.', 'ms')}
        </>
      )}
    </>
  )
}
