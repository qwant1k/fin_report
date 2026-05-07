import { LucideIcon, TrendingDown, TrendingUp } from 'lucide-react'
import clsx from 'clsx'

interface Props {
  title: string
  value: string
  subtitle?: string
  delta?: 'up' | 'down'
  icon?: LucideIcon
}

export default function KpiCard({ title, value, subtitle, delta, icon: Icon }: Props) {
  return (
    <div className="card relative overflow-hidden p-4">
      <div
        className={clsx(
          'absolute inset-x-0 top-0 h-1',
          delta === 'up' ? 'bg-emerald-500' : delta === 'down' ? 'bg-red-500' : 'bg-cyan-500',
        )}
      />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>
          <div
            className={clsx(
              'mt-1 text-2xl font-bold text-slate-950',
              delta === 'up' && 'text-emerald-700',
              delta === 'down' && 'text-red-700',
            )}
          >
            {value}
          </div>
        </div>
        {Icon && (
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
            <Icon className="h-4 w-4" />
          </div>
        )}
      </div>

      {subtitle && (
        <div className="mt-2 flex items-center gap-1 text-xs font-medium text-slate-500">
          {delta === 'up' && <TrendingUp className="w-3 h-3 text-emerald-500" />}
          {delta === 'down' && <TrendingDown className="w-3 h-3 text-red-500" />}
          {subtitle}
        </div>
      )}
    </div>
  )
}
