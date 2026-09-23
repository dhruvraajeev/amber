// Everything the UI asks the backend (§11.5). Phase 0 has no backend, so each call is answered
// locally: `simulate` by the seeded fake, the rest by the same code and files the backend will use.
// Phase 2 swaps these bodies for fetch('/api/...') and removes the "Demo data" badge.

import databases from '@shared/presets/databases.json'
import gpus from '@shared/presets/gpus.json'
import hostedLlms from '@shared/presets/hosted_llms.json'
import models from '@shared/presets/models.json'
import services from '@shared/presets/services.json'
import { validate as check } from '../lib/validate'
import type { Design, RunConfig, ValidationIssue } from '../types/contracts'
import { fakeSimulate } from './fake'

const templates = Object.values(
  import.meta.glob<Design>('@shared/templates/*.json', { eager: true, import: 'default' }),
)

export const simulate = fakeSimulate

export async function validate(design: Design, config?: RunConfig): Promise<ValidationIssue[]> {
  return check(design, config)
}

export async function getPresets() {
  return { gpus, models, hostedLlms, databases, services }
}

export async function getTemplates(): Promise<Design[]> {
  return templates
}
