import { describe, expect, it } from 'vitest'
import { dotCount, dotSeconds, loadColor, loadGlow } from './color'

describe('canvas load colors', () => {
  it('uses the Load tab bands and only theme tokens', () => {
    expect([0.2, 0.7, 0.95].map(loadColor)).toEqual(['var(--ok)', 'var(--warn)', 'var(--crit)'])
    expect(loadGlow(0.95)).toContain('var(--crit)')
    expect(loadGlow(0.95)).not.toMatch(/#|rgba?\(/)
  })

  it('glows harder as load rises', () => {
    const blur = (u: number) => Number(loadGlow(u).split(' ')[2].replace('px', ''))
    expect(blur(0.9)).toBeGreaterThan(blur(0.3))
  })
})

describe('traffic dots', () => {
  it('caps at 8, keeps at least 1 for any traffic, and none for no traffic', () => {
    expect(dotCount(1000, 1000)).toBe(8)
    expect(dotCount(5000, 1000)).toBe(8)
    expect(dotCount(1, 1000)).toBe(1)
    expect(dotCount(0, 1000)).toBe(0)
    expect(dotCount(500, 1000)).toBe(4)
  })

  it('move faster as throughput rises', () => {
    expect(dotSeconds(1000, 1000)).toBeLessThan(dotSeconds(100, 1000))
  })
})
