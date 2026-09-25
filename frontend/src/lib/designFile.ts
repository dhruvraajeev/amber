import { withLayout } from '../canvas/map'
import type { Design } from '../api/api'

// Designs in and out of the editor without a server: a JSON file, or a link whose #d= fragment carries
// the design. The fragment is what Amber's MCP server returns as `open_url` after a simulation, so a
// design an AI agent built opens on the canvas in one click. A fragment never reaches the server.

/** The design in a JSON file or fragment, laid out if it has no positions, or null if it isn't one.
 * Only the shape is checked here; the validator and the run bar report everything else, as for any edit. */
export function parseDesign(text: string): Design | null {
  try {
    const d = JSON.parse(text)
    return isDesign(d) ? withLayout(d) : null
  } catch {
    return null
  }
}

export function isDesign(d: unknown): d is Design {
  const o = d as Design | null
  return o?.version === 1 && Array.isArray(o.nodes) && Array.isArray(o.edges)
}

/** `#d=<base64url of deflate-raw JSON>` → the design, or null when the fragment is missing or broken.
 * mcp/amber_mcp/server.py `open_url` writes this format; keep the two in step. */
export async function designFromHash(hash: string): Promise<Design | null> {
  if (!hash.startsWith('#d=')) return null
  try {
    const b64 = hash.slice(3).replace(/-/g, '+').replace(/_/g, '/')
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'))
    return parseDesign(await new Response(stream).text())
  } catch {
    return null
  }
}

/** Save the design as `<name>.json`, positions included, ready to open again or hand to an agent. */
export function downloadDesign(design: Design): void {
  const url = URL.createObjectURL(new Blob([JSON.stringify(design, null, 2)], { type: 'application/json' }))
  const a = Object.assign(document.createElement('a'), {
    href: url,
    download: `${design.name.replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '') || 'design'}.json`,
  })
  a.click()
  URL.revokeObjectURL(url)
}
