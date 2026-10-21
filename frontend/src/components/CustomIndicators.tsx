import { Link } from 'react-router-dom'
import { AlertTriangle, Sigma } from 'lucide-react'
import clsx from 'clsx'

import { useAuthStore } from '@/lib/auth'
import { formatIndicator, type IndicatorValue } from '@/lib/indicators'

/** Пользовательские показатели в «Сводке»: панель по фонду и плашки в блоке ЧДУ. */

function Chip({ item, dark }: { item: IndicatorValue; dark?: boolean }) {
  return (
    <span
      title={`${item.formula}\n= ${item.substituted}`}
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs ring-1 ring-inset',
        item.alert
          ? 'bg-red-50 text-red-800 ring-red-600/25'
          : dark ? 'bg-white/15 text-white ring-white/20' : 'bg-slate-50 text-slate-700 ring-slate-500/15',
      )}
    >
      {item.alert && <AlertTriangle className="h-3 w-3" />}
      <span className={clsx(dark && !item.alert ? 'text-white/80' : 'text-slate-500')}>{item.name}</span>
      <span className="font-semibold tabular-nums">{formatIndicator(item.value, item.unit, item.decimals)}</span>
    </span>
  )
}

export function CduIndicatorChips({ items }: { items?: IndicatorValue[] }) {
  if (!items?.length) return null
  return (
    <div className="flex flex-wrap items-center gap-1.5 border-b border-slate-100 bg-slate-50/60 px-4 py-2">
      <Sigma className="h-3.5 w-3.5 text-violet-500" />
      {items.map((it) => <Chip key={it.id} item={it} />)}
    </div>
  )
}

export function FundIndicatorsPanel({ items, date }: { items?: IndicatorValue[]; date: string }) {
  const can = useAuthStore((s) => s.can)
  if (!items?.length) return null
  return (
    <div className="card flex flex-wrap items-center gap-2 px-4 py-3">
      <span className="mr-1 inline-flex items-center gap-1.5 text-sm font-semibold text-slate-800">
        <Sigma className="h-4 w-4 text-violet-500" /> Мои показатели по фонду
        <span className="text-xs font-normal text-slate-500">на {new Date(date).toLocaleDateString('ru-RU')}</span>
      </span>
      {items.map((it) => <Chip key={it.id} item={it} />)}
      {can('page.formulas') && (
        <Link to="/formulas?tab=custom" className="ml-auto text-xs font-medium text-emerald-700 hover:underline">
          настроить
        </Link>
      )}
    </div>
  )
}
