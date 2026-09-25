import { describe, expect, it } from 'vitest'
import template from '@shared/templates/agent-self-hosted.json'
import type { Design } from '../api/api'
import { withLayout } from '../canvas/map'
import { designFromHash, parseDesign } from './designFile'

// Written by mcp/amber_mcp/server.py `open_url` for a two-node design named "Tiny ✓", every node at 0,0.
const LINK =
  '#d=jY69CsJAEIRfRaa-wmghXGdpZ6GVSbEmSzhM7uR-guG4d3cJAVPaLDvszLeTYWlkaNyMnXd1OpyqIxQm9sE4C10pWNdxgH5kmE6MSc4vY5c1iE3kQE8eRN9X_XbBxCWe8YHeK8wyixzI0yisXIpacfTDSXoyLW-A5-vlT1yjwF2_7cmVRINLvuW1dSTfc1x-lqZ8AQ'

describe('designs from links and files', () => {
  it('reads the MCP server’s open_url fragment and lays it out', async () => {
    const d = (await designFromHash(LINK))!
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
