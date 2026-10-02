import { motion } from 'framer-motion'
import { type LucideIcon } from 'lucide-react'

import { cn } from '@/lib/cn'

export interface SegmentOption<T extends string> {
  value: T
  label: string
  icon?: LucideIcon
}

interface Props<T extends string> {
  options: SegmentOption<T>[]
  value: T
  onChange: (value: T) => void
  className?: string
  size?: 'sm' | 'md'
  /** Unique id so the sliding indicator animates independently per instance. */
  layoutId?: string
}

/** Animated segmented control with a sliding active indicator (framer-motion shared layout). */
export default function Segmented<T extends string>({
  options,
  value,
  onChange,
  className,
  size = 'md',
  layoutId = 'segmented',
}: Props<T>) {
  return (
    <div
      className={cn(
        'inline-flex flex-wrap items-center gap-1 rounded-xl border border-slate-200 bg-white/80 p-1 shadow-sm backdrop-blur',
        className,
      )}
    >
      {options.map((opt) => {
        const active = opt.value === value
        const Icon = opt.icon
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={cn(
              'relative inline-flex items-center gap-1.5 rounded-lg font-medium transition-colors',
              size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3 py-1.5 text-sm',
              active ? 'text-white' : 'text-slate-600 hover:text-slate-900',
            )}
          >
            {active && (
              <motion.span
                layoutId={layoutId}
                transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                className="absolute inset-0 rounded-lg bg-brand-gradient shadow-sm"
              />
            )}
            <span className="relative z-10 inline-flex items-center gap-1.5">
              {Icon && <Icon className={size === 'sm' ? 'h-3.5 w-3.5' : 'h-4 w-4'} />}
              {opt.label}
            </span>
          </button>
        )
      })}
    </div>
  )
}
