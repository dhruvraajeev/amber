import type { ReactNode } from 'react'
import { Link } from 'react-router'

// Top bar (§11.2). Page-specific controls go in `children`.
// "Demo data" stays until api.ts stops using the fake (phase 2, §11.5).
export default function TopBar({ children }: { children?: ReactNode }) {
  return (
    <header className="flex items-center gap-4 border-b border-border bg-panel px-4 py-2">
      <Link to="/" className="font-semibold text-accent">
        ◈ Amber
      </Link>
      {children}
      <nav className="ml-auto flex items-center gap-4 text-sm">
        <Link to="/compare" className="text-muted hover:text-text">
          Compare
        </Link>
        <span
          className="rounded border border-accent px-2 py-0.5 text-xs text-accent"
          title="Results come from a built-in fake, not the simulator"
        >
          Demo data
        </span>
      </nav>
    </header>
  )
}
