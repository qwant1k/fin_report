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
    <div className="card p-4 flex flex-col gap-1">
      <div className="flex items-center justify-between text-xs text-slate-500 uppercase tracking-wide">
        {title}
        {Icon && <Icon className="w-4 h-4 text-slate-400" />}
      </div>
      <div className={clsx(
        'text-2xl font-bold',
        delta === 'up' && 'text-emerald-600',
        delta === 'down' && 'text-red-600',
      )}>
        {value}
      </div>
      {subtitle && (
        <div className="text-xs text-slate-500 flex items-center gap-1">
          {delta === 'up' && <TrendingUp className="w-3 h-3 text-emerald-500" />}
          {delta === 'down' && <TrendingDown className="w-3 h-3 text-red-500" />}
          {subtitle}
        </div>
      )}
    </div>
  )
}
