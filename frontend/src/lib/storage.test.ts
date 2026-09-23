import { afterEach, describe, expect, it, vi } from 'vitest'
import { load, save } from './storage'

afterEach(() => vi.unstubAllGlobals())

describe('storage', () => {
  it('round-trips JSON', () => {
    const m = new Map<string, string>()
    vi.stubGlobal('localStorage', { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => m.set(k, v) })
    save('k', { a: 1 })
    expect(load('k')).toEqual({ a: 1 })
    expect(load('missing')).toBeNull()
  })

  it('never throws when storage is blocked or corrupt', () => {
    const boom = () => { throw new DOMException('blocked', 'SecurityError') }
    vi.stubGlobal('localStorage', { getItem: boom, setItem: boom })
    expect(() => save('k', 1)).not.toThrow()
    expect(load('k')).toBeNull()
    vi.stubGlobal('localStorage', { getItem: () => '{not json' })
    expect(load('k')).toBeNull()
  })
})
