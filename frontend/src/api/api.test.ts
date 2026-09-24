import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, simulate, validate } from './api'

// Answers every fetch with `status` and `body` (a string is sent as is, anything else as JSON).
const answer = (status: number, body: unknown) =>
  vi.stubGlobal('fetch', vi.fn(async () => new Response(typeof body === 'string' ? body : JSON.stringify(body), { status })))
const refusal = (p: Promise<unknown>) => p.then(() => null, (e: unknown) => e)

const design = { name: 'x', version: 1 as const, nodes: [], edges: [] }
const config = { durationS: 60, seed: 1, warmupS: 5 }

afterEach(() => vi.unstubAllGlobals())

describe('api', () => {
  it('posts {design, config} and returns the body', async () => {
    answer(200, { designHash: 'h' })
    expect(await simulate(design, config)).toEqual({ designHash: 'h' })
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/simulate')
    expect(JSON.parse(init!.body as string)).toEqual({ design, config })
  })

  it('unwraps validate’s issues', async () => {
    answer(200, { issues: [{ code: 'NO_USERS', message: 'm' }] })
    expect(await validate(design)).toEqual([{ code: 'NO_USERS', message: 'm' }])
  })

  it('throws a 422’s issues as they are', async () => {
    const issues = [{ code: 'CYCLE', message: 'm', nodeId: 'n_a' }]
    answer(422, { issues })
    const e = (await refusal(simulate(design, config))) as ApiError
    expect(e.issues).toEqual(issues)
  })

  it('turns {error, detail} into one issue', async () => {
    answer(429, { error: 'rate_limited', detail: 'Too many simulations.' })
    const e = (await refusal(simulate(design, config))) as ApiError
    expect(e.issues).toEqual([{ code: 'rate_limited', message: 'Too many simulations.' }])
  })

  it('has no issues when the answer isn’t ours (no backend behind the proxy)', async () => {
    answer(502, 'Bad Gateway')
    const e = (await refusal(simulate(design, config))) as ApiError
    expect(e).toBeInstanceOf(ApiError)
    expect(e.issues).toEqual([])
  })
})
