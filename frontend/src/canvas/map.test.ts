import { describe, expect, it } from 'vitest'
import template from '@shared/templates/agent-self-hosted.json'
import type { Design } from '../api/api'
import { canonicalDesign, designHash, KINDS, newNode, toFlowEdge, toFlowNode } from './map'

const design = template as Design

describe('design → React Flow mapping', () => {
  it('keeps id, position and the rest as node data', () => {
    const { id, position, ...data } = design.nodes[0]
    expect(toFlowNode(design.nodes[0])).toEqual({ id, position, type: data.kind, data })
  })

  it('shows edge roles as labels', () => {
    const withRole = design.edges.find((e) => e.role)!
    expect(toFlowEdge(withRole).label).toBe(withRole.role)
  })

  it('new nodes get unique ids and every kind has defaults', () => {
    const taken = new Set<string>()
    for (const { kind } of KINDS) {
      const n = newNode(kind, { x: 0, y: 0 }, taken)
      expect(taken.has(n.id)).toBe(false)
      expect(n.kind).toBe(kind)
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
