import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync(new URL('./theme.css', import.meta.url), 'utf8')

function token(name: string): string {
  const m = css.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, 'i'))
  if (!m) throw new Error(`token --${name} missing`)
  return m[1]
}

// WCAG relative luminance — what a greyscale rendering preserves
function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

describe('theme tokens (plan §11.3)', () => {
  it('keeps ok / warn / crit distinguishable in greyscale', () => {
    const [ok, warn, crit] = ['ok', 'warn', 'crit'].map(token)
    for (const [a, b] of [[ok, warn], [warn, crit], [ok, crit]]) {
      expect(contrast(a, b)).toBeGreaterThanOrEqual(1.3)
    }
  })

  it('text and muted meet 4.5:1 on bg and panel', () => {
    for (const fg of ['text', 'muted']) {
      for (const bg of ['bg', 'panel']) {
        expect(contrast(token(fg), token(bg))).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  it('status colors meet 3:1 for graphics on bg', () => {
    for (const s of ['ok', 'warn', 'crit']) {
      expect(contrast(token(s), token('bg'))).toBeGreaterThanOrEqual(3)
    }
  })
})
