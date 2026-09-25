// Everything the UI asks the backend (§9, §11.5). In dev, Vite proxies /api to the backend on :8000.

import type { Design, LlmNode, RunConfig, RunResult, UsersParams, ValidationIssue } from './generated'

// The §7 contracts, generated from the backend's Pydantic models: `npm run gen:types` after changing
// backend/amber/contracts.py. The aliases below name the unions that the schema only has inline.
export type * from './generated'
export type DesignNode = Design['nodes'][number]
export type NodeKind = DesignNode['kind']
export type NodeParamsByKind = { [K in NodeKind]: Extract<DesignNode, { kind: K }>['params'] }
export type TrafficProfile = UsersParams['traffic']
export type LlmParams = LlmNode['params']

export const simulate = (design: Design, config: RunConfig) => call<RunResult>('simulate', { design, config })

export const getTemplates = () => call<Design[]>('templates')

/** A refused request, as issues the run drawer can list: a 422's own, or the `{error, detail}` of a 429, 504, … */
export class ApiError extends Error {
  issues: ValidationIssue[]
  constructor(issues: ValidationIssue[]) {
    super(issues.map((i) => i.message).join(' ') || 'Request failed')
    this.issues = issues
  }
}

async function call<T>(path: string, body?: unknown): Promise<T> {
  const init = body === undefined ? undefined : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
  const res = await fetch(`/api/${path}`, init)
  const json = await res.json().catch(() => null) // a proxy error page, or no backend at all
  if (res.ok && json !== null) return json as T
  if (json?.issues) throw new ApiError(json.issues)
  throw new ApiError(json?.detail ? [{ code: json.error, message: json.detail }] : [])
}
