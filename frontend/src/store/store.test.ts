import { beforeEach, describe, expect, it, vi } from 'vitest'
import classic from '@shared/templates/classic-web-app.json'
import agent from '@shared/templates/agent-self-hosted.json'
import { BLANK } from '../canvas/map'
import type { Design, RunResult } from '../types/contracts'

// The store autosaves to localStorage, so each test gets a fresh in-memory one and a fresh store.
const saved = new Map<string, string>()
vi.stubGlobal('localStorage', { getItem: (k: string) => saved.get(k) ?? null, setItem: (k: string, v: string) => saved.set(k, v) })
vi.mock('../api/api', () => ({ simulate: vi.fn(async () => ({ designHash: 'x' })) }))

const fresh = async () => {
  vi.resetModules()
  return (await import('.')).useStore
}

beforeEach(() => saved.clear())

describe('design slice', () => {
  it('adds, connects with agent roles, and removes nodes with their edges', async () => {
    const s = await fresh()
    s.getState().loadTemplate(BLANK)
    const add = (kind: 'agent' | 'llm' | 'service') => {
      s.getState().addNode(kind, { x: 0, y: 0 })
      return s.getState().selectedId!
    }
    const [a, l, t] = [add('agent'), add('llm'), add('service')]
    s.getState().connect(a, l)
    s.getState().connect(a, t)
    s.getState().connect(a, t) // duplicate: ignored
    s.getState().connect(a, a) // self loop: ignored
    expect(s.getState().design!.edges.map((e) => e.role)).toEqual(['llm', 'tool'])

    s.getState().remove([a])
    expect(s.getState().design!.nodes).toHaveLength(2)
    expect(s.getState().design!.edges).toHaveLength(0)
  })

  it('edits nodes without touching the template it came from', async () => {
    const s = await fresh()
    s.getState().loadTemplate(classic as Design)
    s.getState().updateNode('n_api', { label: 'Edge API' })
    s.getState().moveNode('n_api', { x: 1, y: 2 })
    const api = s.getState().design!.nodes.find((n) => n.id === 'n_api')!
    expect(api).toMatchObject({ label: 'Edge API', position: { x: 1, y: 2 } })
    expect(classic.nodes.find((n) => n.id === 'n_api')!.label).toBe('API')
  })

  it('autosaves and restores the design on the next load', async () => {
    const s = await fresh()
    s.getState().loadTemplate(agent as Design)
    s.getState().setName('Mine')
    const again = await fresh()
    expect(again.getState().design).toEqual({ ...agent, name: 'Mine' })
  })

  it('works with storage blocked', async () => {
    const boom = () => { throw new Error('blocked') }
    vi.stubGlobal('localStorage', { getItem: boom, setItem: boom })
    const s = await fresh()
    expect(s.getState().design).toBeNull()
    s.getState().loadTemplate(classic as Design)
    expect(s.getState().design!.name).toBe(classic.name)
    vi.stubGlobal('localStorage', { getItem: (k: string) => saved.get(k) ?? null, setItem: (k: string, v: string) => saved.set(k, v) })
  })
})

describe('run slice', () => {
  it('refuses an invalid design with its issues', async () => {
    const s = await fresh()
    s.getState().loadTemplate(BLANK)
    await s.getState().run({ durationS: 60, seed: 1, warmupS: 5 })
    expect(s.getState().status).toBe('error')
    expect(s.getState().issues.map((i) => i.code)).toContain('NO_USERS')
  })

  it('runs once even if asked twice, then pins at most two results', async () => {
    const s = await fresh()
    const { simulate } = await import('../api/api')
    s.getState().loadTemplate(classic as Design)
    const config = { durationS: 60, seed: 1, warmupS: 5 }
    await Promise.all([s.getState().run(config), s.getState().run(config)])
    expect(simulate).toHaveBeenCalledTimes(1)
    expect(s.getState().status).toBe('done')
    for (let i = 0; i < 3; i++) {
      await s.getState().run(config)
      s.getState().pin()
    }
    expect(s.getState().pinned).toHaveLength(2)
  })

  it('clamps the playhead and replays from the start once at the end', async () => {
    const s = await fresh()
    const timeline = [0, 1, 2].map((t) => ({ t })) as unknown as RunResult['timeline']
    s.setState({ result: { timeline } as RunResult })
    s.getState().setPlayhead(9)
    expect(s.getState().playhead).toBe(2)
    s.getState().setPlayhead(-1)
    expect(s.getState().playhead).toBe(0)
    s.getState().setPlayhead(2)
    s.getState().togglePlay()
    expect(s.getState()).toMatchObject({ playing: true, playhead: 0 })
    s.getState().togglePlay()
    expect(s.getState().playing).toBe(false)
  })

  it('drops the last result when another design is loaded, but keeps pins', async () => {
    const s = await fresh()
    s.getState().loadTemplate(classic as Design)
    await s.getState().run({ durationS: 60, seed: 1, warmupS: 5 })
    s.getState().pin()
    s.getState().loadTemplate(agent as Design)
    expect(s.getState()).toMatchObject({ status: 'idle', result: null, playhead: 0 })
    expect(s.getState().pinned).toHaveLength(1)
  })
})
