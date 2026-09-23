// React Bits' spotlight card without a component per card: one listener moves --mx/--my to the
// cursor inside whichever `.spotlight` element it is over, and theme.css draws the light.
export function trackSpotlight() {
  document.addEventListener('pointermove', (e) => {
    const el = (e.target as Element | null)?.closest?.<HTMLElement>('.spotlight')
    if (!el) return
    const r = el.getBoundingClientRect()
    el.style.setProperty('--mx', `${e.clientX - r.left}px`)
    el.style.setProperty('--my', `${e.clientY - r.top}px`)
  }, { passive: true })
}
