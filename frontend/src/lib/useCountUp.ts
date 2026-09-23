import { useEffect, useRef, useState } from 'react'

/** Eases from the last shown value to `target` over `ms` (ease-out cubic), React Bits' CountUp idea.
 *  Jumps straight there under prefers-reduced-motion. */
export function useCountUp(target: number, ms = 800): number {
  const [value, setValue] = useState(0)
  const shown = useRef(0)
  useEffect(() => {
    const from = shown.current
    const set = (v: number) => setValue((shown.current = v))
    if (!Number.isFinite(target) || matchMedia('(prefers-reduced-motion: reduce)').matches) return set(target)
    const t0 = performance.now()
    let raf = 0
    const frame = (now: number) => {
      const k = Math.min(1, (now - t0) / ms)
      set(from + (target - from) * (1 - (1 - k) ** 3))
      if (k < 1) raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])
  return value
}
