import { flushSync } from 'react-dom'

// Runs a state change inside a native view transition, so the page cross-fades (theme.css styles it)
// instead of jumping. Browsers without the API just apply the change.
export function transition(update: () => void) {
  if (!('startViewTransition' in document)) return update()
  // A click mid-transition aborts it and `ready` rejects; the update still applies, so that's not an error.
  document.startViewTransition(() => flushSync(update)).ready.catch(() => {})
}
