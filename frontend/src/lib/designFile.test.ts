import { describe, expect, it } from 'vitest'
import template from '@shared/templates/agent-self-hosted.json'
import type { Design } from '../api/api'
import { withLayout } from '../canvas/map'
import { designFromHash, MAX_DESIGN_BYTES, parseDesign } from './designFile'

// The templates, as Amber ships them.
const TEMPLATES = Object.values(import.meta.glob<Design>('@shared/templates/*.json', { eager: true, import: 'default' }))

/** A `#d=` link the way mcp/amber_mcp/server.py `open_url` writes one: deflate-raw, then base64url. */
async function link(text: string): Promise<string> {
  const stream = new Blob([text]).stream().pipeThrough(new CompressionStream('deflate-raw'))
  const bytes = new Uint8Array(await new Response(stream).arrayBuffer())
  let bin = ''
  for (const b of bytes) bin += String.fromCharCode(b)
  return '#d=' + btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

// Written by mcp/amber_mcp/server.py `open_url` for a two-node design named "Tiny ✓", every node at 0,0.
const LINK =
  '#d=jY69CsJAEIRfRaa-wmghXGdpZ6GVSbEmSzhM7uR-guG4d3cJAVPaLDvszLeTYWlkaNyMnXd1OpyqIxQm9sE4C10pWNdxgH5kmE6MSc4vY5c1iE3kQE8eRN9X_XbBxCWe8YHeK8wyixzI0yisXIpacfTDSXoyLW-A5-vlT1yjwF2_7cmVRINLvuW1dSTfc1x-lqZ8AQ'

describe('designs from links and files', () => {
  it('reads the MCP server’s open_url fragment and lays it out', async () => {
    const d = (await designFromHash(LINK)) as Design
    expect(d.name).toBe('Tiny ✓')
    expect(d.nodes.map((n) => [n.id, n.position.x])).toEqual([['u', 0], ['a', 240]])
  })

  it('turns away broken links and non-designs', async () => {
    expect(await designFromHash('#d=not-deflate')).toBeNull()
    expect(await designFromHash(LINK.slice(0, 40))).toBeNull() // cut short when copied
    expect(await designFromHash('')).toBeNull()
    expect(parseDesign('{"name": "x"}')).toBeNull()
    expect(parseDesign('nope')).toBeNull()
  })

  it('opens every template from a link', async () => {
    expect(TEMPLATES.length).toBe(3)
    for (const t of TEMPLATES) expect(await designFromHash(await link(JSON.stringify(t)))).toEqual(t)
  })

  it('refuses a small link that inflates past the cap, without reading it all', async () => {
    const bomb = await link(' '.repeat(2 * MAX_DESIGN_BYTES)) // 2 MB of spaces: a link of a few KB
    expect(bomb.length).toBeLessThan(10_000)
    const started = performance.now()
    expect(await designFromHash(bomb)).toBe('tooLarge')
    expect(performance.now() - started).toBeLessThan(1000)
    // Just under the cap is still read (and then turned away for not being a design).
    expect(await designFromHash(await link(' '.repeat(MAX_DESIGN_BYTES - 1)))).toBeNull()
  })

  it('keeps a design that already has a layout', () => {
    const d = template as Design
    expect(withLayout(d)).toBe(d)
    expect(parseDesign(JSON.stringify(d))).toEqual(d)
  })

  it('lays out by call depth, one column per level, centred', () => {
    const d = template as Design
    const stacked = { ...d, nodes: d.nodes.map((n) => ({ ...n, position: { x: 0, y: 0 } })) }
    const at = Object.fromEntries(withLayout(stacked).nodes.map((n) => [n.id, n.position]))
    const xs = d.nodes.map((n) => at[n.id].x)
    expect(new Set(d.nodes.map((n) => `${at[n.id].x},${at[n.id].y}`)).size).toBe(d.nodes.length) // no overlaps
    expect(Math.min(...xs)).toBe(0) // users first
    for (const e of d.edges) expect(at[e.target].x).toBeGreaterThan(at[e.source].x) // callers left of callees
  })
})
