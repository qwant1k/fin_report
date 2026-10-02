import { LucideIcon } from 'lucide-react'

import StatCard, { type Accent } from './ui/StatCard'

interface Props {
  title: string
  value: string
  subtitle?: string
  delta?: 'up' | 'down'
  icon?: LucideIcon
  accent?: Accent
}

/**
 * Backwards-compatible wrapper around the richer {@link StatCard}.
 * Accepts a pre-formatted string value (no count-up); use StatCard directly
 * with a numeric value when animation is desired.
 */
export default function KpiCard({ title, value, subtitle, delta, icon: Icon, accent }: Props) {
  return (
    <StatCard
      title={title}
      value={value}
      subtitle={subtitle}
      delta={delta}
      icon={Icon}
      accent={accent ?? (delta === 'down' ? 'red' : delta === 'up' ? 'emerald' : 'sky')}
      colorByDelta
    />
  )
}
