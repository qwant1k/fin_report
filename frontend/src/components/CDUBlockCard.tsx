import clsx from 'clsx'

import { CDUBlock } from '@/lib/types'
import { formatNumber, formatPct } from '@/lib/format'

interface Props {
  block: CDUBlock
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

export default function CDUBlockCard({ block }: Props) {
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
              return (
                <tr key={row.category} className={clsx(isBreach && 'breach', !isBreach && isRepo && 'repo')}>
                  <td className="font-medium">{row.label}</td>
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
