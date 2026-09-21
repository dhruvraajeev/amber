import { describe, expect, it } from 'vitest'
import template from '@shared/templates/agent-self-hosted.json'
import type { Design } from '../types/contracts'
import { canonicalDesign, designHash, KINDS, newNode, toDesign, toFlow } from './map'

const design = template as Design

describe('design ↔ React Flow mapping', () => {
  it('round-trips a template unchanged', () => {
    const { nodes, edges } = toFlow(design)
    expect(toDesign(design, nodes, edges)).toEqual(design)
  })

  it('keeps edge roles and drops absent ones', () => {
    const { nodes, edges } = toFlow(design)
    const out = toDesign(design, nodes, edges).edges
    expect(out.filter((e) => e.role).length).toBe(design.edges.filter((e) => e.role).length)
    expect(out.every((e) => 'role' in e === (e.role !== undefined))).toBe(true)
  })

  it('new nodes get unique ids and every kind has defaults', () => {
    const taken = new Set<string>()
    for (const { kind } of KINDS) {
      const n = newNode(kind, { x: 0, y: 0 }, taken)
      expect(taken.has(n.id)).toBe(false)
      expect(n.data.kind).toBe(kind)
      taken.add(n.id)
    }
  })
})

describe('canonical design and hash (position excluded)', () => {
  const moved: Design = { ...design, nodes: design.nodes.map((n) => ({ ...n, position: { x: n.position.x + 99, y: -3 } })) }

  it('has no positions and sorted keys', () => {
    const c = canonicalDesign(design)
    expect(c).not.toContain('position')
    expect(c.startsWith('{"edges":')).toBe(true)
  })

  it('moving nodes does not change the hash', async () => {
    expect(await designHash(moved)).toBe(await designHash(design))
    expect(await designHash(design)).toMatch(/^[0-9a-f]{64}$/)
  })

  it('changing anything else does change the hash', async () => {
    const edited = structuredClone(design)
    edited.nodes[0].label += ' (edited)'
    expect(await designHash(edited)).not.toBe(await designHash(design))
  })

  it('key order in the input does not matter', () => {
    expect(canonicalDesign({ version: 1, edges: design.edges, nodes: design.nodes, name: design.name })).toBe(
      canonicalDesign(design),
    )
  })
})
