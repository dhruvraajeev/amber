// localStorage that never throws (§11.4): private windows, blocked site data, or a full quota
// make reads return null and writes do nothing, and the app carries on without autosave.

export function load(key: string): unknown {
  try {
    const raw = localStorage.getItem(key)
    return raw === null ? null : JSON.parse(raw)
  } catch {
    return null
  }
}

export function save(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // ignore: autosave is a convenience
  }
}
