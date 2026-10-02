import { type LucideIcon, Minus, TrendingDown, TrendingUp } from 'lucide-react'
import { motion } from 'framer-motion'

import { cn } from '@/lib/cn'
import AnimatedNumber from './AnimatedNumber'
import { fadeInUp } from './motion'

export type Accent = 'emerald' | 'sky' | 'amber' | 'red' | 'violet' | 'slate' | 'teal'

const ACCENT: Record<Accent, { bar: string; icon: string; glow: string }> = {
  emerald: { bar: 'from-emerald-500 to-teal-400', icon: 'bg-emerald-50 text-emerald-600', glow: 'group-hover:shadow-emerald-500/10' },
  teal: { bar: 'from-teal-500 to-cyan-400', icon: 'bg-teal-50 text-teal-600', glow: 'group-hover:shadow-teal-500/10' },
  sky: { bar: 'from-sky-500 to-blue-400', icon: 'bg-sky-50 text-sky-600', glow: 'group-hover:shadow-sky-500/10' },
  amber: { bar: 'from-amber-500 to-orange-400', icon: 'bg-amber-50 text-amber-600', glow: 'group-hover:shadow-amber-500/10' },
  red: { bar: 'from-red-500 to-rose-400', icon: 'bg-red-50 text-red-600', glow: 'group-hover:shadow-red-500/10' },
  violet: { bar: 'from-violet-500 to-fuchsia-400', icon: 'bg-violet-50 text-violet-600', glow: 'group-hover:shadow-violet-500/10' },
  slate: { bar: 'from-slate-400 to-slate-300', icon: 'bg-slate-100 text-slate-600', glow: '' },
}

interface Props {
  title: string
  /** Pass a number to animate (count-up); pass a string for static display. */
  value: number | string
  format?: (n: number) => string
  subtitle?: React.ReactNode
  delta?: 'up' | 'down' | 'flat'
  icon?: LucideIcon
  accent?: Accent
  className?: string
  /** When true, value color follows the delta direction. */
  colorByDelta?: boolean
  onClick?: () => void
  active?: boolean
}

export default function StatCard({
  title,
  value,
  format,
  subtitle,
  delta,
  icon: Icon,
  accent = 'emerald',
  className,
  colorByDelta = false,
  onClick,
  active = false,
}: Props) {
  const a = ACCENT[accent]
  const DeltaIcon = delta === 'up' ? TrendingUp : delta === 'down' ? TrendingDown : Minus
  const Component = onClick ? motion.button : motion.div

  return (
    <Component
      variants={fadeInUp}
      type={onClick ? 'button' : undefined}
      onClick={onClick}
      className={cn(
        'group card relative overflow-hidden p-4 text-left transition-all duration-300 hover:-translate-y-1 hover:shadow-card-hover',
        onClick && 'w-full cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2',
        active && 'border-emerald-300 ring-2 ring-emerald-500/20',
        a.glow,
        className,
      )}
    >
      <div className={cn('absolute inset-x-0 top-0 h-1 bg-gradient-to-r', a.bar)} />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>
          <div
            className={cn(
              'mt-1.5 font-display text-2xl font-bold tracking-tight text-slate-900',
              colorByDelta && delta === 'up' && 'text-emerald-700',
              colorByDelta && delta === 'down' && 'text-red-600',
            )}
          >
            {typeof value === 'number' ? <AnimatedNumber value={value} format={format} /> : value}
          </div>
        </div>
        {Icon && (
          <div
            className={cn(
              'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition-transform duration-300 group-hover:scale-110',
              a.icon,
            )}
          >
            <Icon className="h-5 w-5" />
          </div>
        )}
      </div>

      {subtitle && (
        <div
          className={cn(
            'mt-2.5 flex items-center gap-1 text-xs font-medium',
            delta === 'up' ? 'text-emerald-600' : delta === 'down' ? 'text-red-500' : 'text-slate-500',
          )}
        >
          {delta && <DeltaIcon className="h-3.5 w-3.5" />}
          {subtitle}
        </div>
      )}
    </Component>
  )
}
