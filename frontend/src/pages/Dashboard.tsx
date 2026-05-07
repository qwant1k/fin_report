import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Calendar,
  FileSpreadsheet,
  FileText,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  Wallet,
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'

import CDUBlockCard from '@/components/CDUBlockCard'
import HistoryChart from '@/components/HistoryChart'
import KpiCard from '@/components/KpiCard'
import { api } from '@/lib/api'
import { formatDate, formatNumber, formatPct } from '@/lib/format'
import { DashboardResponse } from '@/lib/types'

type PeriodMode = 'all' | 'year' | 'month' | 'week' | 'custom'

const PERIOD_OPTIONS: Array<{ mode: PeriodMode; label: string }> = [
  { mode: 'all', label: 'Весь период' },
  { mode: 'year', label: 'Год' },
  { mode: 'month', label: 'Месяц' },
  { mode: 'week', label: 'Неделя' },
  { mode: 'custom', label: 'Период' },
]

function toIsoDate(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function startOfWeek(date: Date): Date {
  const copy = new Date(date)
  const mondayOffset = (copy.getDay() + 6) % 7
  copy.setDate(copy.getDate() - mondayOffset)
  return copy
}

function getPeriodBounds(mode: PeriodMode, customFrom: string, customTo: string) {
  const today = new Date()
  const to = customTo || toIsoDate(today)

  if (mode === 'all') return { from: undefined, to }
  if (mode === 'year') return { from: `${today.getFullYear()}-01-01`, to }
  if (mode === 'month') {
    const month = String(today.getMonth() + 1).padStart(2, '0')
    return { from: `${today.getFullYear()}-${month}-01`, to }
  }
  if (mode === 'week') return { from: toIsoDate(startOfWeek(today)), to }
  return { from: customFrom || undefined, to }
}

export default function DashboardPage() {
  const today = toIsoDate(new Date())
  const [periodMode, setPeriodMode] = useState<PeriodMode>('all')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState(today)
  const qc = useQueryClient()

  const period = useMemo(
    () => getPeriodBounds(periodMode, customFrom, customTo),
    [periodMode, customFrom, customTo],
  )
  const periodLabel = period.from
    ? `${formatDate(period.from)} - ${formatDate(period.to)}`
    : 'весь доступный период'

  const { data, isLoading, refetch } = useQuery<DashboardResponse>({
    queryKey: ['dashboard', periodMode, period.from, period.to],
    queryFn: async () => {
      const params: Record<string, string> = { to: period.to }
      if (period.from) params.from = period.from
      return (await api.get('/dashboard/summary', { params })).data
    },
  })
  const effectiveReportDate = data?.report_date ?? period.to

  const calc = useMutation({
    mutationFn: async () => (
      await api.post('/calculate/', { report_date: effectiveReportDate, recalculate: true })
    ).data,
    onSuccess: (r) => {
      toast.success(
        `Расчёт за ${formatDate(effectiveReportDate)} завершён за ${r.duration_seconds}с: ЧДУ ${r.cdus_processed}, нарушений ${r.breaches_count}`,
      )
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const downloadXlsx = async () => {
    const resp = await api.get('/export/xlsx', {
      params: { report_date: effectiveReportDate },
      responseType: 'blob',
    })
    const url = URL.createObjectURL(new Blob([resp.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = `risk_report_${effectiveReportDate.replaceAll('-', '')}.xlsx`
    a.click()
    URL.revokeObjectURL(url)
  }

  const downloadPdf = async () => {
    const resp = await api.get('/export/pdf', {
      params: { report_date: effectiveReportDate },
      responseType: 'blob',
    })
    const url = URL.createObjectURL(new Blob([resp.data], { type: 'application/pdf' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `risk_report_${effectiveReportDate.replaceAll('-', '')}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Сводный отчёт Фонда</h1>
          <p className="text-sm text-slate-500">
            Период: <strong>{periodLabel}</strong> · дата среза:{' '}
            <strong>{formatDate(effectiveReportDate)}</strong> · {data?.blocks.length ?? 0} ЧДУ
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <div className="flex flex-wrap rounded-md border border-slate-200 bg-white p-1 shadow-sm">
            {PERIOD_OPTIONS.map((option) => (
              <button
                key={option.mode}
                type="button"
                onClick={() => setPeriodMode(option.mode)}
                className={clsx(
                  'h-9 rounded px-3 text-sm transition',
                  periodMode === option.mode
                    ? 'bg-kdif-green text-white shadow-sm'
                    : 'text-slate-600 hover:bg-slate-100',
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
          {periodMode === 'custom' && (
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Calendar className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  type="date"
                  value={customFrom}
                  onChange={(e) => setCustomFrom(e.target.value)}
                  className="input h-10 w-40 pl-9"
                />
              </div>
              <div className="relative">
                <Calendar className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  type="date"
                  value={customTo}
                  onChange={(e) => setCustomTo(e.target.value)}
                  className="input h-10 w-40 pl-9"
                />
              </div>
            </div>
          )}
          <button onClick={() => refetch()} className="btn-secondary">
            <RefreshCw className="h-4 w-4" /> Обновить
          </button>
          <button onClick={() => calc.mutate()} disabled={calc.isPending} className="btn-primary">
            <RefreshCw className={`h-4 w-4 ${calc.isPending ? 'animate-spin' : ''}`} /> Пересчитать
          </button>
          <button onClick={downloadXlsx} className="btn-secondary">
            <FileSpreadsheet className="h-4 w-4" /> XLSX
          </button>
          <button onClick={downloadPdf} className="btn-secondary">
            <FileText className="h-4 w-4" /> PDF
          </button>
        </div>
      </header>

      <section className="sticky top-0 z-20 -mx-2 grid grid-cols-1 gap-4 bg-slate-50/95 px-2 py-3 backdrop-blur sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Активы Фонда"
          value={formatNumber(data?.fund_total_mv ?? 0, 0) + ' ₸'}
          icon={Wallet}
        />
        <KpiCard
          title="Изменение за день"
          value={formatNumber(data?.fund_daily_change ?? 0, 0) + ' ₸'}
          delta={(data?.fund_daily_change ?? 0) >= 0 ? 'up' : 'down'}
          subtitle={formatPct(data?.fund_daily_change_pct ?? 0)}
          icon={(data?.fund_daily_change ?? 0) >= 0 ? TrendingUp : TrendingDown}
        />
        <KpiCard
          title="YTM (взвеш.)"
          value={formatPct(data?.fund_ytm_weighted ?? 0)}
          subtitle={data?.benchmark_ytm != null ? `MBM: ${formatPct(data.benchmark_ytm)}` : 'MBM: —'}
        />
        <KpiCard
          title="Duration (взвеш.)"
          value={formatNumber(data?.fund_duration_weighted ?? 0, 2)}
          subtitle={data?.benchmark_duration != null ? `MBM: ${formatNumber(data.benchmark_duration, 2)}` : 'MBM: —'}
        />
      </section>

      {data && data.breaches_count > 0 && (
        <div className="card border-l-4 border-red-500 bg-red-50/60 p-4">
          <div className="font-semibold text-red-700">Нарушений лимитов: {data.breaches_count}</div>
          <div className="text-sm text-red-700/80">См. вкладку «Алерты»</div>
        </div>
      )}

      <section className="card p-4">
        <h2 className="mb-3 font-semibold">
          Динамика портфеля {period.from ? `(${periodLabel})` : '(90 дней)'}
        </h2>
        <HistoryChart from={period.from} to={period.to} />
      </section>

      <section className="space-y-6">
        {isLoading && <div className="card p-8 text-center text-slate-500">Загрузка...</div>}
        {!isLoading && data?.blocks.length === 0 && (
          <div className="card p-8 text-center text-slate-500">
            Нет данных за выбранный период. Загрузите файлы и нажмите «Пересчитать».
          </div>
        )}
        {data?.blocks.map((block) => (
          <CDUBlockCard
            key={block.cdu_id}
            block={block}
            periodFrom={period.from}
            periodTo={period.to}
          />
        ))}
      </section>
    </div>
  )
}
