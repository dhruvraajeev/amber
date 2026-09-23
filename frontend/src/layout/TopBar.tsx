import { GitCompareArrows, Info } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router'

// Top bar (§11.2): the mark, page-specific controls (`children`), then Compare, the model assumptions,
// and the "Demo data" badge, which stays until api.ts stops using the fake (phase 2, §11.5).
// "Model" opens the assumptions (§8.11) in a native popover: Esc and clicking outside close it.
export default function TopBar({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return (
    <header className={`flex min-w-0 items-center gap-3 px-1 ${className}`}>
      <Link to="/" className="flex shrink-0 items-center gap-2.5 pr-2" aria-label="Amber home">
        <Mark />
        <span className="text-[15px] font-semibold tracking-[-0.01em]">Amber</span>
      </Link>
      {children}
      <nav className="ml-auto flex shrink-0 items-center gap-2">
        <NavLink
          to="/compare"
          className={({ isActive }) =>
            `field flex h-9 items-center gap-2 rounded-full px-3.5 text-[13px] ${isActive ? 'border-border-strong text-text' : 'text-muted hover:text-text'}`}
        >
          <GitCompareArrows size={15} aria-hidden />
          Compare
        </NavLink>
        <button popoverTarget="model-assumptions" className="field flex h-9 items-center gap-2 rounded-full px-3.5 text-[13px] text-muted hover:text-text">
          <Info size={15} aria-hidden />
          Model
        </button>
        <span
          className="flex h-9 items-center gap-2 rounded-full border border-accent/30 bg-accent/10 px-3.5 text-[13px] text-accent-2"
          title="Results come from a built-in fake, not the simulator"
        >
          <span className="pulse-dot size-1.5 bg-accent text-accent" aria-hidden />
          Demo data
        </span>
      </nav>
      <div
        id="model-assumptions"
        popover="auto"
        className="panel fixed inset-auto top-16 right-4 m-0 max-w-md p-5 text-[13px] text-text"
      >
        <h2 className="text-[15px] font-semibold">Model assumptions</h2>
        <p className="mt-1 text-muted">Amber is a model, not a benchmark. It simplifies on purpose:</p>
        <ul className="mt-3 flex flex-col gap-2">
          {ASSUMPTIONS.map((a) => (
            <li key={a} className="flex gap-2.5 leading-snug">
              <span className="mt-[7px] size-1 shrink-0 rounded-full bg-accent" aria-hidden />
              {a}
            </li>
          ))}
        </ul>
      </div>
    </header>
  )
}

/** Amber's mark: a faceted ember, orange on top, red below, with a white glint. */
function Mark() {
  return (
    <svg viewBox="0 0 32 32" className="size-7 drop-shadow-[0_4px_12px_rgb(255_106_43/0.45)]" aria-hidden>
      <defs>
        <linearGradient id="mark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ff9a5c" />
          <stop offset="0.55" stopColor="#ff6a2b" />
          <stop offset="1" stopColor="#c42a24" />
        </linearGradient>
      </defs>
      <path d="M16 2 28 12 16 30 4 12Z" fill="url(#mark-fill)" />
      <path d="M16 2 22 12 16 30 10 12Z" fill="#000" opacity="0.18" />
      <path d="M4 12h24" stroke="#fff" strokeOpacity="0.35" strokeWidth="1" />
      <path d="M16 2 10 12h12Z" fill="#fff" opacity="0.28" />
    </svg>
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
