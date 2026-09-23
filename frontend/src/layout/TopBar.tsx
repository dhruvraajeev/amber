import type { ReactNode } from 'react'
import { Link } from 'react-router'

// Top bar (§11.2). Page-specific controls go in `children`.
// "Demo data" stays until api.ts stops using the fake (phase 2, §11.5).
// "ⓘ Model" opens the model assumptions (§8.11) in a native popover: Esc and clicking outside close it.
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
        <button popoverTarget="model-assumptions" className="text-muted hover:text-text">
          ⓘ Model
        </button>
        <span
          className="rounded border border-accent px-2 py-0.5 text-xs text-accent"
          title="Results come from a built-in fake, not the simulator"
        >
          Demo data
        </span>
      </nav>
      <div
        id="model-assumptions"
        popover="auto"
        className="fixed inset-auto top-12 right-4 m-0 max-w-md rounded-lg border border-border bg-panel p-4 text-sm text-text shadow-lg"
      >
        <h2 className="font-semibold">Model assumptions</h2>
        <p className="mt-1 text-muted">Amber is a model, not a benchmark. It simplifies on purpose:</p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {ASSUMPTIONS.map((a) => <li key={a}>{a}</li>)}
        </ul>
      </div>
    </header>
  )
}

// Plan §8.11, in plain words. docs/simulation-model.md (Step 16) carries the same list.
const ASSUMPTIONS = [
  'Users keep arriving at the set rate no matter how slow the system gets (open-loop traffic).',
  'Calls are synchronous: a caller waits for everything downstream to finish.',
  'Services hold one thread per request for its whole duration, downstream calls included.',
  'Network time is not modeled separately; fold it into each latency setting.',
  'Self-hosted LLMs never preempt a request once admitted; requests that don’t fit wait.',
  'Prefill and decode times grow linearly with tokens and batch size.',
  'Hosted LLM APIs have unlimited concurrency; only their rate limit turns requests away.',
  'Percentiles over long runs are approximate, because the timeline is downsampled.',
  'Monthly cost assumes the simulated traffic pattern repeats all month.',
]
