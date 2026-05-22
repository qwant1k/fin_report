import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Calendar,
  ChevronDown,
  ClipboardCheck,
  Filter,
  FileSpreadsheet,
  FileText,
  Flag,
  Layers,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  Wallet,
  X,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import clsx from 'clsx'
import toast from 'react-hot-toast'

import CDUBlockCard from '@/components/CDUBlockCard'
import HistoryChart from '@/components/HistoryChart'
import KpiCard from '@/components/KpiCard'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { formatDate, formatNumber, formatPct } from '@/lib/format'
import { DashboardResponse } from '@/lib/types'

type PeriodMode = 'all' | 'year' | 'month' | 'week' | 'custom'

interface DashboardCduOption {
  id: number
  name: string
  short_name: string
  portfolio_type: string
}

interface DashboardHistoryMeta {
  cdus: DashboardCduOption[]
}

const PERIOD_OPTIONS: Array<{ mode: PeriodMode; label: string }> = [
  { mode: 'all', label: 'Весь период' },
  { mode: 'year', label: 'Год' },
  { mode: 'month', label: 'Месяц' },
  { mode: 'week', label: 'Неделя' },
  { mode: 'custom', label: 'Период' },
]

const PORTFOLIO_TYPE_OPTIONS = [
  { value: '', label: 'Все портфели' },
  { value: 'PRIVATE_CDU', label: 'Частные ДУ' },
  { value: 'NBRK_OWN', label: 'НБ РК собственные' },
  { value: 'NBRK_RESERVE', label: 'НБ РК спецрезерв' },
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
  const [historyPortfolioType, setHistoryPortfolioType] = useState('')
  const [historyCduIds, setHistoryCduIds] = useState<number[]>([])
  const [isHistoryOpen, setIsHistoryOpen] = useState(false)
  const qc = useQueryClient()
  const can = useAuthStore((s) => s.can)

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
  const historyMeta = useQuery<DashboardHistoryMeta>({
    queryKey: ['dashboard-history-meta'],
    queryFn: async () => (await api.get('/analytics/meta')).data,
  })
  const effectiveReportDate = data?.report_date ?? period.to

  const historyCdus = useMemo(() => {
    const cdus = historyMeta.data?.cdus ?? []
    if (!historyPortfolioType) return cdus
    return cdus.filter((cdu) => cdu.portfolio_type === historyPortfolioType)
  }, [historyMeta.data?.cdus, historyPortfolioType])

  useEffect(() => {
    if (!historyPortfolioType || !historyMeta.data?.cdus.length) return
    const allowed = new Set(historyCdus.map((cdu) => cdu.id))
    setHistoryCduIds((ids) => ids.filter((id) => allowed.has(id)))
  }, [historyCdus, historyMeta.data?.cdus?.length, historyPortfolioType])

  const toggleHistoryCdu = (id: number) => {
    setHistoryCduIds((ids) => (
      ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id]
    ))
  }

  const resetHistoryFilters = () => {
    setHistoryPortfolioType('')
    setHistoryCduIds([])
  }

  const activeHistoryFilters = (historyPortfolioType ? 1 : 0) + historyCduIds.length

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
          {can('dashboard.calculate') && (
          <button onClick={() => calc.mutate()} disabled={calc.isPending} className="btn-primary">
            <RefreshCw className={`h-4 w-4 ${calc.isPending ? 'animate-spin' : ''}`} /> Пересчитать
          </button>
          )}
          {can('reports.export') && (
            <>
          <button onClick={downloadXlsx} className="btn-secondary">
            <FileSpreadsheet className="h-4 w-4" /> XLSX
          </button>
          <button onClick={downloadPdf} className="btn-secondary">
            <FileText className="h-4 w-4" /> PDF
          </button>
            </>
          )}
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
          subtitle={data?.benchmark_ytm != null ? `MBM index: ${formatNumber(data.benchmark_ytm, 2)}` : 'MBM index: —'}
        />
        <KpiCard
          title="Duration (взвеш.)"
          value={formatNumber(data?.fund_duration_weighted ?? 0, 2)}
          subtitle={data?.benchmark_duration != null ? `MBM: ${formatNumber(data.benchmark_duration, 2)}` : 'MBM: —'}
        />
      </section>

      {/* Operational KPIs (Phase 3) — render only if there is something to act on */}
      {data && (data.breaches_count > 0
                || (data.pending_approvals_count ?? 0) > 0
                || (data.flagged_prices_count ?? 0) > 0) && (
        <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {data.breaches_count > 0 && (
            <div className="card border-l-4 border-red-500 bg-red-50/60 p-4">
              <div className="flex items-center gap-2 text-red-700">
                <AlertTriangle className="w-4 h-4" />
                <span className="font-semibold">Нарушения лимитов</span>
              </div>
              <div className="mt-1 text-2xl font-bold text-red-700">{data.breaches_count}</div>
              <Link to="/alerts" className="text-xs text-red-700/80 hover:underline">
                Перейти к алертам →
              </Link>
            </div>
          )}
          {(data.pending_approvals_count ?? 0) > 0 && (
            <div className="card border-l-4 border-amber-500 bg-amber-50/60 p-4">
              <div className="flex items-center gap-2 text-amber-800">
                <ClipboardCheck className="w-4 h-4" />
                <span className="font-semibold">Ждут утверждения</span>
              </div>
              <div className="mt-1 text-2xl font-bold text-amber-800">{data.pending_approvals_count}</div>
              <Link to="/reports?status=pending_approval" className="text-xs text-amber-800/80 hover:underline">
                Открыть отчёты →
              </Link>
            </div>
          )}
          {(data.flagged_prices_count ?? 0) > 0 && (
            <div className="card border-l-4 border-orange-500 bg-orange-50/60 p-4">
              <div className="flex items-center gap-2 text-orange-700">
                <Flag className="w-4 h-4" />
                <span className="font-semibold">Цена заменена на KASE</span>
              </div>
              <div className="mt-1 text-2xl font-bold text-orange-700">{data.flagged_prices_count}</div>
              <div className="text-xs text-orange-700/80">сделок за {formatDate(effectiveReportDate)}</div>
            </div>
          )}
        </section>
      )}

      <section className="card p-4">
        <button
          type="button"
          onClick={() => setIsHistoryOpen((open) => !open)}
          className="flex w-full items-center justify-between gap-3 text-left"
          aria-expanded={isHistoryOpen}
        >
          <span className="font-semibold">
          Динамика портфеля {period.from ? `(${periodLabel})` : '(90 дней)'}
          </span>
          <span className="flex items-center gap-3 text-sm font-medium text-slate-500">
            {isHistoryOpen ? 'Скрыть' : 'Показать'}
            {activeHistoryFilters > 0 && (
              <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">
                {activeHistoryFilters}
              </span>
            )}
            <ChevronDown className={clsx('h-5 w-5 transition-transform', isHistoryOpen && 'rotate-180')} />
          </span>
        </button>

        {isHistoryOpen && (
          <>
        <div className="mb-4 mt-4 rounded-lg border border-slate-200 bg-slate-50/70 p-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
              <Filter className="h-4 w-4 text-emerald-600" />
              Фильтры графика
              {activeHistoryFilters > 0 && (
                <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">
                  {activeHistoryFilters}
                </span>
              )}
            </div>
            {activeHistoryFilters > 0 && (
              <button type="button" onClick={resetHistoryFilters} className="btn-secondary h-8 px-2 text-xs">
                <X className="h-3.5 w-3.5" />
                Сбросить
              </button>
            )}
          </div>

          <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-[280px_1fr]">
            <label className="text-sm">
              <span className="label flex items-center gap-1.5">
                <Layers className="h-3.5 w-3.5" />
                Тип портфеля
              </span>
              <select
                className="input h-10"
                value={historyPortfolioType}
                onChange={(e) => setHistoryPortfolioType(e.target.value)}
              >
                {PORTFOLIO_TYPE_OPTIONS.map((option) => (
                  <option key={option.value || 'all'} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <div>
              <div className="label">ЧДУ</div>
              <div className="flex max-h-24 flex-wrap gap-2 overflow-auto rounded-lg border border-slate-200 bg-white p-2">
                {historyCdus.length === 0 ? (
                  <div className="px-2 py-1 text-sm text-slate-500">Нет ЧДУ для выбранного типа</div>
                ) : historyCdus.map((cdu) => (
                  <label
                    key={cdu.id}
                    className={clsx(
                      'flex min-h-8 items-center gap-2 rounded-md border px-2.5 py-1 text-sm font-medium transition',
                      historyCduIds.includes(cdu.id)
                        ? 'border-emerald-500 bg-emerald-50 text-emerald-800'
                        : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-100',
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={historyCduIds.includes(cdu.id)}
                      onChange={() => toggleHistoryCdu(cdu.id)}
                      className="h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                    />
                    {cdu.short_name}
                  </label>
                ))}
              </div>
            </div>
          </div>
        </div>

        <HistoryChart
          from={period.from}
          to={period.to}
          portfolioType={historyPortfolioType}
          cduIds={historyCduIds}
        />
          </>
        )}
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
