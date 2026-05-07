import { Fragment, useEffect, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import clsx from 'clsx'

import { api } from '@/lib/api'
import { CategoryRow, CDUBlock, InstrumentDetailRow } from '@/lib/types'
import { formatDate, formatNumber, formatPct } from '@/lib/format'

interface Props {
  block: CDUBlock
  periodFrom?: string
  periodTo: string
}

const COLUMN_LABELS = [
  'Инструменты',
  'MV T-1',
  'Δ за день',
  'CMV',
  '% портф.',
  'YTM',
  'Duration',
  'Min',
  'Max',
  'Hard',
  'Soft',
  'Свободно (млн ₸)',
]

export default function CDUBlockCard({ block, periodFrom, periodTo }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)

  return (
    <div className="card overflow-hidden">
      <div className="bg-kdif-green text-white px-4 py-3 font-semibold flex items-center justify-between">
        <span>{block.cdu_name}</span>
        <span className="text-xs font-normal opacity-80">
          Доля в Фонде: {formatPct(block.cdu_share_pct)}
        </span>
      </div>
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
                        <InstrumentDetails
                          block={block}
                          row={row}
                          periodFrom={periodFrom}
                          periodTo={periodTo}
                        />
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
          <span className="text-slate-500">Duration портфеля:</span>
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

function InstrumentDetails({
  block,
  row,
  periodFrom,
  periodTo,
}: {
  block: CDUBlock
  row: CategoryRow
  periodFrom?: string
  periodTo: string
}) {
  const [from, setFrom] = useState(periodFrom ?? '')
  const [to, setTo] = useState(periodTo)
  const [items, setItems] = useState<InstrumentDetailRow[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setFrom(periodFrom ?? '')
    setTo(periodTo)
  }, [periodFrom, periodTo])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const params: Record<string, string | number> = {
          cdu_id: block.cdu_id,
          category: row.category,
          to,
        }
        if (from) params.from = from
        const res = await api.get('/dashboard/instrument-details', { params })
        if (!cancelled) setItems(res.data.rows ?? [])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [block.cdu_id, row.category, from, to])

  return (
    <div className="space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-700">{row.label}</div>
          <div className="text-xs text-slate-500">{block.cdu_name}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="input h-9 w-40" />
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="input h-9 w-40" />
        </div>
      </div>

      <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
        <table className="w-full table-fixed text-sm">
          <thead className="bg-slate-100 text-xs text-slate-600">
            <tr>
              <th className="w-36 px-3 py-2 text-left">Код</th>
              <th className="w-36 px-3 py-2 text-left">ISIN</th>
              <th className="w-44 px-3 py-2 text-right">Количество</th>
              <th className="w-44 px-3 py-2 text-right">Номинал</th>
              <th className="w-44 px-3 py-2 text-right">Сумма</th>
              <th className="w-24 px-3 py-2 text-right">YTM</th>
              <th className="w-24 px-3 py-2 text-right">Duration</th>
              <th className="w-32 px-3 py-2 text-left">Первая дата</th>
              <th className="w-32 px-3 py-2 text-left">Последняя дата</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={`${item.instrument_code}-${item.isin ?? ''}`} className="border-t border-slate-100">
                <td className="px-3 py-2 font-mono text-xs">{item.instrument_code}</td>
                <td className="px-3 py-2 font-mono text-xs">{item.isin ?? '—'}</td>
                <td className="px-3 py-2 text-right">{formatNumber(item.quantity, 2)}</td>
                <td className="px-3 py-2 text-right">{formatNumber(item.face_value, 0)}</td>
                <td className="px-3 py-2 text-right font-medium">{formatNumber(item.amount, 0)}</td>
                <td className="px-3 py-2 text-right">{item.ytm != null ? formatPct(item.ytm) : '—'}</td>
                <td className="px-3 py-2 text-right">{item.duration != null ? formatNumber(item.duration, 2) : '—'}</td>
                <td className="px-3 py-2">{item.first_date ? formatDate(item.first_date) : '—'}</td>
                <td className="px-3 py-2">{item.last_date ? formatDate(item.last_date) : '—'}</td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-center text-slate-400">Нет детализации за выбранный период</td>
              </tr>
            )}
            {loading && (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-center text-slate-400">Загрузка…</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
