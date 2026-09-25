import { useEffect, useRef } from 'react'

const WISP = 16 // copies drawn along each mote's recent path, fading: its wisp

type Mote = { x: number; y: number; r: number; rise: number; sway: number; phase: number; age: number; life: number; tint: number }

// The landing page's backdrop: faint ember motes drifting up and swaying, each trailing a short wisp.
// A mote's path is a function of its age, so the wisp is just fading copies at earlier ages. Canvas 2D, no library.
// Reduced motion gets one still frame.
export default function Embers({ className = '' }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current!
    const ctx = canvas.getContext('2d')!
    const css = getComputedStyle(document.documentElement)
    const sprites = ['--accent', '--ember', '--series-4'].map((token) => sprite(css.getPropertyValue(token).trim()))
    const still = matchMedia('(prefers-reduced-motion: reduce)').matches
    let w = 0
    let h = 0
    let motes: Mote[] = []
    let raf = 0
    let last = 0

    const spawn = (anywhere: boolean): Mote => {
      const life = 6 + Math.random() * 8
      return {
        x: Math.random() * w,
        y: anywhere ? Math.random() * h : h * (0.5 + Math.random() * 0.6), // where it starts; it rises from here
        r: 0.5 + Math.random() * 1.4,
        rise: 6 + Math.random() * 16, // px per second
        sway: 6 + Math.random() * 18,
        phase: Math.random() * Math.PI * 2,
        age: anywhere ? Math.random() * life : 0,
        life,
        tint: Math.random() < 0.55 ? 0 : Math.random() < 0.6 ? 1 : 2,
      }
    }

    const draw = (dt: number) => {
      ctx.clearRect(0, 0, w, h)
      ctx.globalCompositeOperation = 'lighter'
      for (let i = 0; i < motes.length; i++) {
        let m = motes[i]
        m.age += dt
        if (m.age > m.life) m = motes[i] = spawn(false)
        const fade = 0.36 * Math.sin((Math.PI * m.age) / m.life) // in, then out
        for (let k = 0; k < WISP; k++) {
          const t = m.age - k * 0.14 // where the mote was a moment ago
          const x = m.x + Math.sin(m.phase + t * 0.6) * m.sway
          const y = m.y - m.rise * t
          const size = m.r * 9 * (1 - k / (WISP + 2))
          ctx.globalAlpha = fade * (1 - k / WISP) ** 2
          ctx.drawImage(sprites[m.tint], x - size / 2, y - size / 2, size, size)
        }
      }
      ctx.globalAlpha = 1
    }

    const tick = (t: number) => {
      draw(last ? Math.min((t - last) / 1000, 0.05) : 0)
      last = t
      raf = requestAnimationFrame(tick)
    }

    const resize = () => {
      const dpr = Math.min(devicePixelRatio, 2)
      w = canvas.clientWidth
      h = canvas.clientHeight
      canvas.width = w * dpr
      canvas.height = h * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      motes = Array.from({ length: Math.min(70, Math.round((w * h) / 16000)) }, () => spawn(true))
      if (still) draw(0)
    }

    const observer = new ResizeObserver(resize)
    observer.observe(canvas)
    if (!still) raf = requestAnimationFrame(tick)
    return () => {
      observer.disconnect()
      cancelAnimationFrame(raf)
    }
  }, [])

  return <canvas ref={ref} className={className} aria-hidden />
}

/** A soft round glow in one theme color (`#rrggbb`), drawn once and stamped for every mote. */
function sprite(hex: string) {
  const s = 64
  const c = document.createElement('canvas')
  c.width = c.height = s
  const g = c.getContext('2d')!
  const [r, gr, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
  const glow = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2)
  glow.addColorStop(0, `rgb(${r} ${gr} ${b} / 1)`)
  glow.addColorStop(0.18, `rgb(${r} ${gr} ${b} / 0.45)`)
  glow.addColorStop(1, `rgb(${r} ${gr} ${b} / 0)`)
  g.fillStyle = glow
  g.fillRect(0, 0, s, s)
  return c
}
