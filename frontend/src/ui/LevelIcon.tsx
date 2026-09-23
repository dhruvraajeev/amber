import { Circle, CircleAlert, TriangleAlert, type LucideProps } from 'lucide-react'
import type { Level } from '../lib/format'

const ICONS = { ok: Circle, warn: TriangleAlert, crit: CircleAlert }

/** Status is never hue alone (§11.3): each load level has its own shape, drawn in its color. */
export default function LevelIcon({ level, ...props }: { level: Level } & LucideProps) {
  const Icon = ICONS[level]
  return <Icon aria-hidden size={12} strokeWidth={2.25} color={`var(--${level})`} {...props} />
}
