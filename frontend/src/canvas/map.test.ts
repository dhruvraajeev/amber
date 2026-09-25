import { describe, expect, it } from 'vitest'
import template from '@shared/templates/agent-self-hosted.json'
import type { Design } from '../api/api'
import { KINDS, newNode, toFlowEdge, toFlowNode } from './map'

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
