import { type LucideIcon } from 'lucide-react'
import { motion } from 'framer-motion'

import { cn } from '@/lib/cn'
import { EASE } from './motion'

interface Props {
  title: string
  subtitle?: React.ReactNode
  icon?: LucideIcon
  actions?: React.ReactNode
  className?: string
}

/** Consistent, animated page header with an optional icon and actions slot. */
export default function PageHeader({ title, subtitle, icon: Icon, actions, className }: Props) {
  return (
    <motion.header
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: EASE }}
      className={cn('flex flex-wrap items-start justify-between gap-4', className)}
    >
      <div className="flex items-start gap-3">
        {Icon && (
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-brand-gradient text-white shadow-soft">
            <Icon className="h-5 w-5" />
          </div>
        )}
        <div className="min-w-0">
          <h1 className="text-2xl font-bold leading-tight text-slate-900">{title}</h1>
          {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center justify-end gap-2">{actions}</div>}
    </motion.header>
  )
}
