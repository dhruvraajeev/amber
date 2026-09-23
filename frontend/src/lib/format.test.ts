import { describe, expect, it } from 'vitest'
import { count, level, ms, pct, rps, usd } from './format'

describe('format', () => {
  it('prints units and groups thousands', () => {
    expect([ms(42.4), ms(1240), ms(12_500)]).toEqual(['42 ms', '1,240 ms', '12.5 s'])
    expect([pct(0.923), pct(0.0123, 1)]).toEqual(['92%', '1.2%'])
    expect([usd(0), usd(0.42), usd(4210.4)]).toEqual(['$0', '$0.42', '$4,210'])
    expect([rps(4.52), rps(200)]).toEqual(['4.5 req/s', '200 req/s'])
    expect(count(12000.4)).toBe('12,000')
  })

  it('bands load at 0.6 and 0.85', () => {
    expect([0, 0.59, 0.6, 0.84, 0.85, 3].map(level)).toEqual(['ok', 'ok', 'warn', 'warn', 'crit', 'crit'])
  })
})
