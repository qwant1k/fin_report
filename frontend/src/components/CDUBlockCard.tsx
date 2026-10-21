import { Fragment, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import clsx from 'clsx'

import { CDUBlock } from '@/lib/types'
import { formatNumber, formatPct } from '@/lib/format'
import CategoryBreakdown from '@/components/CategoryBreakdown'
import { CduIndicatorChips } from '@/components/CustomIndicators'
import type { IndicatorValue } from '@/lib/indicators'

interface Props {
  block: CDUBlock
  periodFrom?: string
  periodTo: string
  indicators?: IndicatorValue[]
}

const COLUMN_LABELS = [
  'Инструменты',
  'MV T-1',
  'Δ за день',
  'CMV',
  '% портф.',
  'YTM',
  'Дюрация',
  'Min',
  'Max',
  'Hard',
  'Soft',
  'Свободно (млн ₸)',
]

export default function CDUBlockCard({ block, periodTo, indicators }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)

  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between gap-3 bg-brand-gradient px-4 py-3 font-semibold text-white">
        <span className="flex items-center gap-2">
          <span className="inline-flex h-2 w-2 rounded-full bg-white/70" />
          {block.cdu_name}
        </span>
        <span className="flex items-center gap-2">
          {block.is_stale && block.as_of_date && (
            <span
              className="rounded-full bg-amber-400 px-2.5 py-0.5 text-xs font-semibold text-amber-950"
              title="Для этого ЧДУ нет расчёта на выбранную дату — показан последний доступный срез"
            >
              Данные на {new Date(block.as_of_date).toLocaleDateString('ru-RU')}
            </span>
          )}
          <span className="rounded-full bg-white/15 px-2.5 py-0.5 text-xs font-medium backdrop-blur">
            Доля в Фонде: {formatPct(block.cdu_share_pct)}
          </span>
        </span>
      </div>
      {!block.is_stale && <CduIndicatorChips items={indicators} />}
      <div className="table-wrap">
        <table className="kdif-table">
          <thead>
            <tr>
              {COLUMN_LABELS.map((label) => (
                <th key={label}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row) => {
              const isRepo = row.category === 'REVERSE_REPO'
              const isBreach = row.hard_limit === 'breach'
              const isOpen = expanded === row.category
              return (
                <Fragment key={row.category}>
                  <tr className={clsx(isBreach && 'breach', !isBreach && isRepo && 'repo')}>
                    <td className="font-medium">
                      <button
                        type="button"
                        onClick={() => setExpanded(isOpen ? null : row.category)}
                        className="inline-flex min-w-0 items-center gap-2 text-left hover:text-emerald-700"
                        title="Показать расшифровку: позиции, даты, цены и источники"
                      >
                        {isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
                        <span>{row.label}</span>
                      </button>
                    </td>
                    <td className="text-right">{formatNumber(row.market_value_prev, 0)}</td>
                    <td className={clsx('text-right', row.daily_change > 0 && 'text-emerald-600',
                      row.daily_change < 0 && 'text-red-600')}>
                      {formatNumber(row.daily_change, 0)}
                    </td>
                    <td className="text-right font-semibold">{formatNumber(row.market_value_current, 0)}</td>
                    <td className="text-right">{formatPct(row.pct_of_total)}</td>
                    <td className="text-right">{row.ytm != null ? formatPct(row.ytm) : '—'}</td>
                    <td className="text-right">{row.duration != null ? formatNumber(row.duration, 2) : '—'}</td>
                    <td className="text-right">{formatPct(row.min_limit_pct)}</td>
                    <td className="text-right">{formatPct(row.max_limit_pct)}</td>
                    <td>
                      <span className={row.hard_limit === 'ok' ? 'badge-ok' : 'badge-breach'}>
                        {row.hard_limit}
                      </span>
                    </td>
                    <td>
                      <span className={row.soft_limit === 'ok' ? 'badge-ok' : 'badge-warn'}>
                        {row.soft_limit}
                      </span>
                    </td>
                    <td className="text-right">{row.free_limit_mln != null ? formatNumber(row.free_limit_mln, 1) : '—'}</td>
                  </tr>
                  {isOpen && (
                    <tr key={`${row.category}-details`}>
                      <td colSpan={12} className="bg-slate-50 p-0">
                        <CategoryBreakdown cduId={block.cdu_id} category={row.category} date={block.as_of_date || periodTo} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
            <tr className="total">
              <td>Total:</td>
              <td className="text-right">{formatNumber(block.total_mv_prev, 0)}</td>
              <td className="text-right">{formatNumber(block.total_daily_change, 0)}</td>
              <td className="text-right">{formatNumber(block.total_mv_current, 0)}</td>
              <td className="text-right">100,00%</td>
              <td className="text-right">{formatPct(block.ytm_weighted)}</td>
              <td className="text-right">{formatNumber(block.duration_weighted, 2)}</td>
              <td colSpan={5}></td>
            </tr>
          </tbody>
        </table>
      </div>

      {block.benchmark_duration != null && (
        <div className="px-4 py-3 border-t border-slate-200 text-sm flex flex-wrap items-center gap-x-6 gap-y-1">
          <span className="text-slate-500">Дюрация портфеля:</span>
          <span className="font-semibold">{formatNumber(block.duration_weighted, 2)}</span>
          <span className="text-slate-500">benchmark MBM:</span>
          <span className="font-semibold">{formatNumber(block.benchmark_duration, 2)}</span>
          <span className="text-slate-500">диапазон:</span>
          <span>
            [{formatNumber(block.duration_lower, 2)}; {formatNumber(block.duration_upper, 2)}]
          </span>
          <span className={block.duration_status === 'breach' ? 'badge-breach' : 'badge-ok'}>
            {block.duration_status ?? 'ok'}
          </span>
        </div>
      )}
    </div>
  )
}
