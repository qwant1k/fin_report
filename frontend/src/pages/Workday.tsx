import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  ClipboardCheck,
  FileSearch,
  FileSpreadsheet,
  FileText,
  GitCompare,
  ListChecks,
  Plus,
  RefreshCw,
  ShieldAlert,
  UploadCloud,
  XCircle,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { downloadBlob } from '@/lib/download'
import { useAuthStore } from '@/lib/auth'
import { useWorkContextStore } from '@/lib/workContext'
import { formatDate, formatNumber, formatPct } from '@/lib/format'
import { EmptyState, PageHeader, StatCard } from '@/components/ui'
import DayProcessTimeline, { type DayProcessStep, type StepStatus } from '@/components/workday/DayProcessTimeline'
import QuickUpload from '@/components/workday/QuickUpload'
import OperationWizard from '@/components/OperationWizard'
import { useUploadProgress } from '@/lib/uploadQueue'
import {
  categoryLabel,
  documentTypeLabel,
  operationLabel,
  processStatusLabel,
  reportTypeLabel,
  workflowStatusLabel,
} from '@/lib/displayLabels'
import { apiErrorMessage } from '@/lib/notifications'

interface WorkdayCdu {
  cdu_id: number
  name: string
  short_name: string
  portfolio_type: string
  trade_files_count: number
  documents_count: number
  operations_count: number
  flagged_prices_count: number
  has_summary: boolean
  status: 'ready' | 'loaded' | 'missing'
  last_file: string | null
  last_upload_at: string | null
  latest_document: string | null
  latest_document_date: string | null
  market_value: number | null
  daily_change: number | null
  ytm_weighted: number | null
  duration_weighted: number | null
  reconciliation_status?: string | null
  open_alerts?: number
}

const RECON_LABEL: Record<string, { text: string; cls: string }> = {
  OK: { text: 'сверка OK', cls: 'text-emerald-700' },
  MATCHED: { text: 'сверка OK', cls: 'text-emerald-700' },
  PENDING: { text: 'сверка: нет данных', cls: 'text-slate-500' },
  MISMATCH: { text: 'расхождение сверки', cls: 'text-red-700 font-semibold' },
  ERROR: { text: 'ошибка сверки', cls: 'text-red-700 font-semibold' },
}

interface WorkdayDocType {
  doc_type: string
  count: number
  rows_imported: number
}

interface WorkdayDocument {
  id: number
  doc_type: string
  file_name: string
  doc_date: string | null
  parse_status: string
  rows_imported: number
  uploaded_at: string | null
}

interface WorkdayReport {
  id: number
  report_type: string
  status: string
  version: number
  generated_at: string | null
  generated_by: string | null
}

interface WorkdaySummary {
  work_date: string
  active_cdus: number
  loaded_cdus: number
  ready_cdus: number
  operations_count: number
  summaries_count: number
  documents_by_type: WorkdayDocType[]
  recent_documents: WorkdayDocument[]
  reports: WorkdayReport[]
  fund_total_mv: number
  fund_daily_change: number
  cdus: WorkdayCdu[]
}

interface RawTradeRow {
  id: number
  cdu_short: string | null
  cdu_name: string | null
  source_file: string | null
  trade_date: string | null
  deal_number: string | null
  order_number: string | null
  trade_time: string | null
  kp: string | null
  operation_type: string | null
  participant_code: string | null
  regime_code: string | null
  instrument_code: string | null
  instrument_category: string | null
  price: number | null
  lots: number | null
  volume: number | null
  settlement_date: string | null
  yield_pct: number | null
  repo_rate_pct: number | null
  repo_sum: number | null
  repo_buyback_sum: number | null
  repo_term_days: number | null
  currency_code: string | null
  status: string | null
  nominal_volume: number | null
}

interface RawTradesResponse {
  from: string
  to: string
  rows_total: number
  rows: RawTradeRow[]
}

type WorkdayDetail = { type: 'readiness' | 'operations' | 'assets' | 'reports' | 'documents'; docType?: string } | null

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

const STATUS_META = {
  ready: {
    label: 'Готов',
    icon: CheckCircle2,
    className: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  },
  loaded: {
    label: 'Нужен расчет',
    icon: AlertTriangle,
    className: 'bg-amber-50 text-amber-700 ring-amber-600/20',
  },
  missing: {
    label: 'Нет данных',
    icon: XCircle,
    className: 'bg-slate-100 text-slate-600 ring-slate-500/20',
  },
} as const

interface ReconciliationLite {
  recon_date: string
  status: string
}

interface AlertLite {
  alert_date: string
  is_resolved: boolean
  severity: 'INFO' | 'WARN' | 'CRITICAL'
}

export default function WorkdayPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const can = useAuthStore((s) => s.can)
  // Единый контекст даты для всего приложения (см. lib/workContext.ts) — раньше
  // дата выбиралась локально на каждом экране, теперь она общая для Рабочего дня,
  // Позиций, KASE, Сверки и Отчётов.
  const workDate = useWorkContextStore((s) => s.workDate)
  const [detail, setDetail] = useState<WorkdayDetail>(null)
  const [wizardOpen, setWizardOpen] = useState(false)

  const summary = useQuery<WorkdaySummary>({
    queryKey: ['workday', workDate],
    queryFn: async () => (
      await api.get('/workday/summary', {
        params: workDate ? { work_date: workDate } : undefined,
      })
    ).data,
  })

  const data = summary.data
  const effectiveWorkDate = workDate || data?.work_date || todayIso()
  const rawTrades = useQuery<RawTradesResponse>({
    queryKey: ['workday-raw-trades', effectiveWorkDate, detail?.type],
    enabled: detail?.type === 'operations',
    queryFn: async () => (await api.get('/operations/raw-trades', { params: { trade_date: effectiveWorkDate } })).data,
  })
  // Реальные данные сверки и алертов за дату — используются для шагов таймлайна ниже.
  const reconciliation = useQuery<ReconciliationLite[]>({
    queryKey: ['workday-reconciliation'],
    queryFn: async () => (await api.get('/reconciliation/list')).data,
  })
  const alerts = useQuery<AlertLite[]>({
    queryKey: ['workday-alerts'],
    queryFn: async () => (await api.get('/dashboard/alerts', { params: { since_days: 60 } })).data,
  })
  const uploadProgress = useUploadProgress()
  // как только очередная загрузка завершилась — обновляем сводку дня
  useEffect(() => {
    if (uploadProgress.done + uploadProgress.failed > 0) qc.invalidateQueries({ queryKey: ['workday'] })
  }, [uploadProgress.done, uploadProgress.failed, qc])
  const missingCdus = useMemo(() => data?.cdus.filter((c) => c.status === 'missing') ?? [], [data])
  const loadedButUncalculated = useMemo(() => data?.cdus.filter((c) => c.status === 'loaded') ?? [], [data])
  const flaggedCount = useMemo(
    () => data?.cdus.reduce((sum, cdu) => sum + cdu.flagged_prices_count, 0) ?? 0,
    [data],
  )
  const reconciliationForDate = useMemo(
    () => (reconciliation.data ?? []).filter((r) => r.recon_date === effectiveWorkDate),
    [reconciliation.data, effectiveWorkDate],
  )
  const mismatches = useMemo(
    () => reconciliationForDate.filter((r) => r.status === 'MISMATCH' || r.status === 'ERROR'),
    [reconciliationForDate],
  )
  const alertsForDate = useMemo(
    () => (alerts.data ?? []).filter((a) => a.alert_date === effectiveWorkDate),
    [alerts.data, effectiveWorkDate],
  )
  const unresolvedAlerts = useMemo(() => alertsForDate.filter((a) => !a.is_resolved), [alertsForDate])
  const unresolvedCritical = useMemo(() => unresolvedAlerts.filter((a) => a.severity === 'CRITICAL'), [unresolvedAlerts])

  useEffect(() => {
    setDetail(null)
  }, [effectiveWorkDate])

  const recalc = useMutation({
    mutationFn: async () => (await api.post('/calculate/', { report_date: effectiveWorkDate, recalculate: true })).data,
    onSuccess: (result) => {
      toast.success(`Расчёт завершён: обработано ЧДУ ${result.cdus_processed}, найдено нарушений ${result.breaches_count}.`)
      qc.invalidateQueries({ queryKey: ['workday'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, `Не удалось выполнить расчёт за ${formatDate(effectiveWorkDate)}`)),
  })

  // Coupons / redemptions / FIFO control / AR closing + calculation for the
  // work date (the scheduler does the same nightly, with catch-up of missed days).
  const dailyAutomation = useMutation({
    mutationFn: async () =>
      (await api.post('/automation/daily-run', { target_date: effectiveWorkDate }, { timeout: 300_000 })).data,
    onSuccess: (result) => {
      const coupons = result?.coupons?.trades ?? 0
      const redemptions = result?.redemptions?.trades ?? 0
      const ar = result?.ar_close?.closed ?? 0
      toast.success(`Автоматическая обработка завершена: купонов ${coupons}, погашений ${redemptions}, закрыто задолженностей ${ar}.`)
      qc.invalidateQueries({ queryKey: ['workday'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, `Не удалось выполнить автоматическую обработку за ${formatDate(effectiveWorkDate)}`)),
  })

  const exportReport = useMutation({
    mutationFn: async (type: 'xlsx' | 'pdf') => {
      const resp = await api.get(`/export/${type}`, {
        params: { report_date: effectiveWorkDate },
        responseType: 'blob',
      })
      downloadBlob(resp.data, `risk_report_${effectiveWorkDate.replaceAll('-', '')}.${type}`)
      return type
    },
    onSuccess: (type) => {
      toast.success(`Отчёт за ${formatDate(effectiveWorkDate)} сформирован и скачан в формате ${type.toUpperCase()}.`)
      qc.invalidateQueries({ queryKey: ['workday'] })
      qc.invalidateQueries({ queryKey: ['reports'] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, `Не удалось сформировать отчёт за ${formatDate(effectiveWorkDate)}`)),
  })

  // Единый операционный центр рабочего дня: 5 стадий вместо перехода по 6-8 экранам.
  // Статусы считаются из реальных данных (/workday/summary, /reconciliation/list, /dashboard/alerts),
  // а не имитируются — так таймлайн не может "соврать" про реальное состояние дня.
  const steps: DayProcessStep[] = useMemo(() => {
    if (!data) return []

    const uploadsRunning = uploadProgress.active + uploadProgress.waiting > 0
    const uploadStatus: StepStatus =
      missingCdus.length === 0 && !uploadsRunning ? 'done' : data.loaded_cdus > 0 || uploadsRunning ? 'in_progress' : 'pending'
    const calcStatus: StepStatus =
      data.active_cdus > 0 && data.ready_cdus === data.active_cdus ? 'done' : data.loaded_cdus > 0 ? 'in_progress' : 'pending'
    const reconStatus: StepStatus = mismatches.length > 0 ? 'error' : reconciliationForDate.length > 0 ? 'done' : 'pending'
    const alertsStatus: StepStatus = unresolvedCritical.length > 0 ? 'error' : unresolvedAlerts.length > 0 ? 'warning' : 'done'
    const reportDone = data.reports.some((r) => r.status === 'approved')
    const reportStatus: StepStatus = reportDone
      ? 'done'
      : unresolvedCritical.length > 0
        ? 'blocked'
        : data.reports.length > 0
          ? 'in_progress'
          : 'pending'

    return [
      {
        id: 'upload',
        title: 'Загрузка',
        icon: UploadCloud,
        status: uploadStatus,
        // загружены не все ЧДУ — это не повод стоять: следующие шаги доступны сразу
        nonBlocking: data.loaded_cdus > 0 || uploadsRunning,
        busy: uploadsRunning,
        meta: uploadsRunning
          ? `идёт загрузка ${uploadProgress.done}/${uploadProgress.total} · ${data.loaded_cdus}/${data.active_cdus} ЧДУ`
          : `${data.loaded_cdus}/${data.active_cdus} ЧДУ загружено`,
        action: uploadStatus !== 'done' && (can('upload.trade_report') || can('primary_data.upload'))
          ? { label: 'Открыть загрузку', onClick: () => navigate('/documents') }
          : undefined,
        detail: (
          <div>
            <p className="text-sm text-slate-600">
              {missingCdus.length > 0
                ? `Нет данных по ${missingCdus.length} ЧДУ: ${missingCdus.map((c) => c.short_name).join(', ')}.`
                : 'Документы получены по всем активным ЧДУ.'}
              {missingCdus.length > 0 && data.loaded_cdus > 0 && ' Остальные шаги уже доступны — недостающие документы можно догрузить позже.'}
            </p>
            {(can('upload.trade_report') || can('primary_data.upload')) && (
              <QuickUpload workDate={effectiveWorkDate} />
            )}
          </div>
        ),
      },
      {
        id: 'parsing',
        title: 'Парсинг и расчёт',
        icon: FileSearch,
        status: calcStatus,
        // все загруженные ЧДУ рассчитаны — недостающие не мешают сверке и отчёту
        nonBlocking: data.ready_cdus > 0 && data.ready_cdus >= data.loaded_cdus,
        meta: `${data.ready_cdus}/${data.active_cdus} ЧДУ рассчитано · KASE/MBM обновляются по расписанию`,
        action: calcStatus !== 'done' && can('dashboard.calculate')
          ? { label: 'Пересчитать', onClick: () => recalc.mutate() }
          : undefined,
        detail: (
          <p className="text-sm text-slate-600">
            {flaggedCount > 0
              ? `${flaggedCount} цен заменены на цену KASE при импорте — проверьте расхождения перед сверкой.`
              : 'Расхождений цен с KASE при импорте не обнаружено.'}
          </p>
        ),
      },
      {
        id: 'reconciliation',
        title: 'Сверка',
        icon: GitCompare,
        status: reconStatus,
        issuesCount: mismatches.length,
        meta: reconciliationForDate.length ? `${reconciliationForDate.length} проверок за дату` : 'Сверка за дату ещё не запускалась',
        action: can('reconciliation.run')
          ? { label: mismatches.length > 0 ? 'Разобрать расхождения' : 'Открыть сверку', onClick: () => navigate('/reconciliation') }
          : undefined,
      },
      {
        id: 'alerts',
        title: 'Алерты и лимиты',
        icon: ShieldAlert,
        status: alertsStatus,
        issuesCount: unresolvedAlerts.length,
        meta: unresolvedAlerts.length > 0 ? `${unresolvedAlerts.length} непогашенных нарушений` : 'Нарушений лимитов нет',
        action: unresolvedAlerts.length > 0 ? { label: 'Просмотреть нарушения', onClick: () => navigate('/alerts') } : undefined,
      },
      {
        id: 'report',
        title: 'Генерация отчёта',
        icon: FileText,
        status: reportStatus,
        meta: data.reports[0]
          ? `${reportTypeLabel(data.reports[0].report_type)} v${data.reports[0].version} · ${workflowStatusLabel(data.reports[0].status)}`
          : 'Отчёты ещё не выпускались',
        blockedReason:
          reportStatus === 'blocked'
            ? 'Есть неразрешённые критические нарушения лимитов — сначала закройте их на шаге «Алерты и лимиты».'
            : undefined,
        action: can('reports.export')
          ? { label: 'Сформировать XLSX', onClick: () => exportReport.mutate('xlsx') }
          : undefined,
      },
    ]
  }, [
    data, missingCdus, mismatches, reconciliationForDate, unresolvedAlerts, unresolvedCritical,
    flaggedCount, can, recalc, exportReport, navigate, uploadProgress, effectiveWorkDate,
  ])

  const openStepFullScreen = (stepId: string) => {
    const routeByStep: Record<string, string> = {
      upload: '/documents',
      parsing: '/positions',
      reconciliation: '/reconciliation',
      alerts: '/alerts',
      report: '/reports',
    }
    navigate(routeByStep[stepId] ?? '/')
  }

  return (
    <div className="space-y-6">
      <PageHeader
        icon={ClipboardCheck}
        title="Рабочий день"
        subtitle="Ежедневный контроль загрузки, расчета портфеля и выпуска отчетов"
        actions={
          <button className="btn-secondary" onClick={() => summary.refetch()}>
            <RefreshCw className={`h-4 w-4 ${summary.isFetching ? 'animate-spin' : ''}`} />
            Обновить
          </button>
        }
      />

      <DayProcessTimeline steps={steps} onOpenFullScreen={openStepFullScreen} />
      <OperationWizard open={wizardOpen} onClose={() => setWizardOpen(false)} />

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="Готовность ЧДУ"
          value={`${data?.ready_cdus ?? 0}/${data?.active_cdus ?? 0}`}
          subtitle={`${data?.loaded_cdus ?? 0} с загруженными данными`}
          icon={CheckCircle2}
          accent={(data?.ready_cdus ?? 0) === (data?.active_cdus ?? 0) && data?.active_cdus ? 'emerald' : 'amber'}
          active={detail?.type === 'readiness'}
          onClick={() => setDetail({ type: 'readiness' })}
        />
        <StatCard
          title="Операции за день"
          value={data?.operations_count ?? 0}
          format={(n) => formatNumber(n, 0)}
          subtitle={flaggedCount > 0 ? `${flaggedCount} цен заменены на KASE` : 'Сверка цен без флагов'}
          icon={ListChecks}
          accent={flaggedCount > 0 ? 'amber' : 'teal'}
          active={detail?.type === 'operations'}
          onClick={() => setDetail({ type: 'operations' })}
        />
        <StatCard
          title="Активы по расчету"
          value={data?.fund_total_mv ?? 0}
          format={(n) => `${formatNumber(n, 0)} ₸`}
          subtitle={`Изменение: ${formatNumber(data?.fund_daily_change ?? 0, 0)} ₸`}
          icon={BarChart3}
          accent="sky"
          active={detail?.type === 'assets'}
          onClick={() => setDetail({ type: 'assets' })}
        />
        <StatCard
          title="Отчеты"
          value={data?.reports.length ?? 0}
          format={(n) => formatNumber(n, 0)}
          subtitle={data?.reports[0] ? `${reportTypeLabel(data.reports[0].report_type)} v${data.reports[0].version}` : 'Еще не выпускались'}
          icon={FileText}
          accent="violet"
          active={detail?.type === 'reports'}
          onClick={() => setDetail({ type: 'reports' })}
        />
      </section>

      {detail && data && (
        <WorkdayDetailPanel
          detail={detail}
          data={data}
          date={effectiveWorkDate}
          rawTrades={rawTrades.data?.rows ?? []}
          rawTradesTotal={rawTrades.data?.rows_total ?? 0}
          rawTradesLoading={rawTrades.isFetching}
          canExport={can('reports.export')}
          exporting={exportReport.isPending}
          onBack={() => setDetail(null)}
          onExport={(type) => exportReport.mutate(type)}
        />
      )}

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-[1.3fr_0.7fr]">
        <div className="card overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-4">
            <div>
              <h2 className="section-title">Контроль по ЧДУ</h2>
              <p className="text-sm text-slate-500">От загрузки файлов до рассчитанного среза портфеля</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {(can('upload.trade_report') || can('primary_data.upload')) && (
                <Link to="/documents" className="btn-secondary">
                  <UploadCloud className="h-4 w-4" />
                  Загрузить документы
                </Link>
              )}
              {(can('manual.cash.manage') || can('manual.trades.manage')) && (
                <button className="btn-secondary" onClick={() => setWizardOpen(true)}
                  title="Поступление денег, покупка ЦБ, закрытие дебиторки и другие ручные операции">
                  <Plus className="h-4 w-4" />
                  Новая операция
                </button>
              )}
              {can('automation.run') && (
                <button
                  className="btn-secondary"
                  onClick={() => dailyAutomation.mutate()}
                  disabled={dailyAutomation.isPending}
                  title="Купоны и погашения на дату, контроль FIFO, закрытие дебиторки, расчёт портфеля"
                >
                  <RefreshCw className={`h-4 w-4 ${dailyAutomation.isPending ? 'animate-spin' : ''}`} />
                  Купоны/погашения
                </button>
              )}
              {can('dashboard.calculate') && (
                <button className="btn-primary" onClick={() => recalc.mutate()} disabled={recalc.isPending}>
                  <RefreshCw className={`h-4 w-4 ${recalc.isPending ? 'animate-spin' : ''}`} />
                  Пересчитать
                </button>
              )}
            </div>
          </div>

          <div className="table-wrap">
            <table className="kdif-table">
              <thead>
                <tr>
                  <th>ЧДУ</th>
                  <th>Документы</th>
                  <th>Операции</th>
                  <th>Расчет</th>
                  <th>MV</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {(data?.cdus ?? []).map((cdu) => {
                  const meta = STATUS_META[cdu.status]
                  const Icon = meta.icon
                  return (
                    <tr key={cdu.cdu_id}>
                      <td>
                        <div className="font-semibold text-slate-800">{cdu.short_name}</div>
                        <div className="max-w-[260px] truncate text-xs text-slate-500" title={cdu.name}>{cdu.name}</div>
                      </td>
                      <td>
                        <div className="text-sm font-medium">{cdu.trade_files_count + cdu.documents_count}</div>
                        <div className="max-w-[220px] truncate text-xs text-slate-500" title={cdu.last_file ?? cdu.latest_document ?? ''}>
                          {cdu.last_file ?? cdu.latest_document ?? 'нет файлов'}
                        </div>
                      </td>
                      <td>
                        <Link to={`/operations?date=${effectiveWorkDate}&cdu_id=${cdu.cdu_id}`} className="font-semibold text-emerald-700 hover:underline">
                          {formatNumber(cdu.operations_count, 0)}
                        </Link>
                        {cdu.flagged_prices_count > 0 && (
                          <div className="text-xs text-amber-700">{cdu.flagged_prices_count} KASE-флагов</div>
                        )}
                      </td>
                      <td>
                        {cdu.has_summary ? 'есть' : 'нет'}
                        {cdu.reconciliation_status && RECON_LABEL[cdu.reconciliation_status] && (
                          <div className={`text-xs ${RECON_LABEL[cdu.reconciliation_status].cls}`}>
                            {RECON_LABEL[cdu.reconciliation_status].text}
                          </div>
                        )}
                        {(cdu.open_alerts ?? 0) > 0 && (
                          <div className="text-xs text-amber-700">алертов: {cdu.open_alerts}</div>
                        )}
                      </td>
                      <td className="text-right">{cdu.market_value == null ? '—' : formatNumber(cdu.market_value, 0)}</td>
                      <td>
                        <span className={`badge ${meta.className}`}>
                          <Icon className="h-3.5 w-3.5" />
                          {meta.label}
                        </span>
                      </td>
                    </tr>
                  )
                })}
                {!data?.cdus.length && (
                  <tr>
                    <td colSpan={6} className="py-10 text-center text-slate-400">Нет активных ЧДУ</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="space-y-4">
          <div className="card p-4">
            <h2 className="section-title">Следующие действия</h2>
            <div className="mt-3 space-y-2">
              <ActionRow
                tone={missingCdus.length > 0 ? 'warn' : 'ok'}
                title={missingCdus.length > 0 ? `Нет данных по ${missingCdus.length} ЧДУ` : 'Все ЧДУ имеют входные данные'}
                text={missingCdus.length > 0 ? missingCdus.map((c) => c.short_name).join(', ') : 'Можно переходить к расчету и отчетам'}
                to="/documents"
              />
              <ActionRow
                tone={loadedButUncalculated.length > 0 ? 'warn' : 'ok'}
                title={loadedButUncalculated.length > 0 ? 'Нужен пересчет' : 'Расчеты актуальны'}
                text={loadedButUncalculated.length > 0 ? loadedButUncalculated.map((c) => c.short_name).join(', ') : 'Сводные строки сформированы'}
                onClick={can('dashboard.calculate') ? () => recalc.mutate() : undefined}
              />
              <ActionRow
                tone={data?.reports.length ? 'ok' : 'neutral'}
                title={data?.reports.length ? 'Отчеты сформированы' : 'Отчеты еще не сформированы'}
                text={data?.reports.map((r) => `${reportTypeLabel(r.report_type)} v${r.version}`).join(', ') || 'Сформируйте отчёт Excel или PDF после проверки'}
                to="/reports"
              />
            </div>
          </div>

          <div className="card p-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="section-title">Выпуск отчета</h2>
              <Link to="/reports" className="text-sm font-medium text-emerald-700 hover:underline">История</Link>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <button
                className="btn-secondary justify-center"
                disabled={!can('reports.export') || exportReport.isPending}
                onClick={() => exportReport.mutate('xlsx')}
              >
                <FileSpreadsheet className="h-4 w-4" />
                XLSX
              </button>
              <button
                className="btn-secondary justify-center"
                disabled={!can('reports.export') || exportReport.isPending}
                onClick={() => exportReport.mutate('pdf')}
              >
                <FileText className="h-4 w-4" />
                PDF
              </button>
            </div>
          </div>

          <div className="card p-4">
            <h2 className="section-title">Документы дня</h2>
            <div className="mt-3 space-y-2">
              {(data?.documents_by_type ?? []).map((doc) => (
                <button
                  key={doc.doc_type}
                  type="button"
                  onClick={() => setDetail({ type: 'documents', docType: doc.doc_type })}
                  className="flex w-full items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-left transition hover:border-emerald-200 hover:bg-emerald-50"
                >
                  <div>
                    <div className="text-sm font-semibold">{documentTypeLabel(doc.doc_type)}</div>
                    <div className="text-xs text-slate-500">строк: {formatNumber(doc.rows_imported, 0)}</div>
                  </div>
                  <span className="badge-neutral">{doc.count}</span>
                </button>
              ))}
              {!data?.documents_by_type.length && (
                <EmptyState
                  icon={FileSpreadsheet}
                  title="Документов за дату нет"
                  description="Загрузите отчёт о сделках или пакет первичных документов."
                  className="py-8"
                />
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="card overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 p-4">
          <div>
            <h2 className="section-title">Последние документы за {formatDate(effectiveWorkDate)}</h2>
            <p className="text-sm text-slate-500">Аудиторский след: файл, статус парсинга и количество импортированных строк</p>
          </div>
        </div>
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>Файл</th>
                <th>Тип</th>
                <th>Статус</th>
                <th>Строк</th>
                <th>Загружен</th>
              </tr>
            </thead>
            <tbody>
              {(data?.recent_documents ?? []).map((doc) => (
                <tr key={doc.id}>
                  <td className="max-w-[420px] truncate font-medium" title={doc.file_name}>{doc.file_name}</td>
                  <td>{documentTypeLabel(doc.doc_type)}</td>
                  <td>{processStatusLabel(doc.parse_status)}</td>
                  <td className="text-right">{formatNumber(doc.rows_imported, 0)}</td>
                  <td>{formatDate(doc.uploaded_at)}</td>
                </tr>
              ))}
              {!data?.recent_documents.length && (
                <tr>
                  <td colSpan={5} className="py-10 text-center text-slate-400">Документов за выбранную дату пока нет</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

function WorkdayDetailPanel({
  detail,
  data,
  date,
  rawTrades,
  rawTradesTotal,
  rawTradesLoading,
  canExport,
  exporting,
  onBack,
  onExport,
}: {
  detail: Exclude<WorkdayDetail, null>
  data: WorkdaySummary
  date: string
  rawTrades: RawTradeRow[]
  rawTradesTotal: number
  rawTradesLoading: boolean
  canExport: boolean
  exporting: boolean
  onBack: () => void
  onExport: (type: 'xlsx' | 'pdf') => void
}) {
  const documents = detail.type === 'documents' && detail.docType
    ? data.recent_documents.filter((doc) => doc.doc_type === detail.docType)
    : data.recent_documents
  const titleByType: Record<Exclude<WorkdayDetail, null>['type'], string> = {
    readiness: 'Детализация готовности ЧДУ',
    operations: 'Операции за день из отчёта о сделках',
    assets: 'Активы по расчёту',
    reports: 'Отчёты за дату',
    documents: 'Документы дня',
  }

  return (
    <section className="card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-4">
        <div>
          <h2 className="section-title">{titleByType[detail.type]}</h2>
          <p className="text-sm text-slate-500">Дата: {formatDate(date)}</p>
        </div>
        <button type="button" onClick={onBack} className="btn-secondary">
          <ArrowLeft className="h-4 w-4" />
          Назад
        </button>
      </div>

      {detail.type === 'readiness' && (
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>ЧДУ</th>
                <th>Статус</th>
                <th>Документы</th>
                <th>Операции</th>
                <th>Расчёт</th>
                <th>Последний файл</th>
              </tr>
            </thead>
            <tbody>
              {data.cdus.map((cdu) => (
                <tr key={cdu.cdu_id}>
                  <td>
                    <div className="font-semibold">{cdu.short_name}</div>
                    <div className="text-xs text-slate-500">{cdu.name}</div>
                  </td>
                  <td>{STATUS_META[cdu.status].label}</td>
                  <td>{formatNumber(cdu.trade_files_count + cdu.documents_count, 0)}</td>
                  <td>{formatNumber(cdu.operations_count, 0)}</td>
                  <td>{cdu.has_summary ? 'есть' : 'нет'}</td>
                  <td className="max-w-[360px] truncate" title={cdu.last_file ?? cdu.latest_document ?? ''}>
                    {cdu.last_file ?? cdu.latest_document ?? 'нет файлов'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detail.type === 'operations' && (
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>Дата</th>
                <th>ЧДУ</th>
                <th>Сделка / заявка</th>
                <th>К/П</th>
                <th>Режим</th>
                <th>Инструмент</th>
                <th>Цена</th>
                <th>Объём</th>
                <th>Доходность</th>
                <th>РЕПО</th>
                <th>Файл</th>
              </tr>
            </thead>
            <tbody>
              {rawTrades.map((row) => (
                <tr key={row.id}>
                  <td>
                    <div>{formatDate(row.trade_date)}</div>
                    <div className="text-xs text-slate-500">{row.trade_time ?? ''}</div>
                  </td>
                  <td>{row.cdu_short ?? row.cdu_name ?? '—'}</td>
                  <td>
                    <div>{row.deal_number ?? '—'}</div>
                    <div className="text-xs text-slate-500">{row.order_number ?? ''}</div>
                  </td>
                  <td>{row.kp ?? '—'}</td>
                  <td>{row.regime_code ?? '—'}</td>
                  <td>
                    <div className="font-medium">{row.instrument_code ?? '—'}</div>
                    <div className="text-xs text-slate-500">{row.instrument_category ? categoryLabel(row.instrument_category) : row.operation_type ? operationLabel(row.operation_type) : ''}</div>
                  </td>
                  <td className="text-right">{formatNumber(row.price, 4)}</td>
                  <td className="text-right">
                    <div>{formatNumber(row.volume, 2)}</div>
                    {row.nominal_volume != null && <div className="text-xs text-slate-500">ном. {formatNumber(row.nominal_volume, 0)}</div>}
                  </td>
                  <td className="text-right">{formatNumber(row.yield_pct, 4)}</td>
                  <td className="text-right">
                    {row.repo_rate_pct != null ? (
                      <>
                        <div>{formatNumber(row.repo_rate_pct, 4)}%</div>
                        <div className="text-xs text-slate-500">{row.repo_term_days ?? '—'} дн.</div>
                      </>
                    ) : '—'}
                  </td>
                  <td className="max-w-[260px] truncate" title={row.source_file ?? ''}>{row.source_file ?? '—'}</td>
                </tr>
              ))}
              {!rawTradesLoading && rawTrades.length === 0 && (
                <tr>
                  <td colSpan={11} className="py-10 text-center text-slate-400">
                    Исходных строк отчёта о сделках за выбранную дату нет.
                  </td>
                </tr>
              )}
              {rawTradesLoading && (
                <tr>
                  <td colSpan={11} className="py-10 text-center text-slate-400">Загрузка...</td>
                </tr>
              )}
            </tbody>
          </table>
          {rawTradesTotal > rawTrades.length && (
            <div className="border-t border-slate-100 px-4 py-2 text-xs text-slate-500">
              Показано {formatNumber(rawTrades.length, 0)} из {formatNumber(rawTradesTotal, 0)} строк.
            </div>
          )}
        </div>
      )}

      {detail.type === 'assets' && (
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>ЧДУ</th>
                <th>MV</th>
                <th>Изменение</th>
                <th>YTM</th>
                <th>Дюрация</th>
                <th>Документ</th>
              </tr>
            </thead>
            <tbody>
              {data.cdus.filter((cdu) => cdu.has_summary).map((cdu) => (
                <tr key={cdu.cdu_id}>
                  <td>
                    <div className="font-semibold">{cdu.short_name}</div>
                    <div className="text-xs text-slate-500">{cdu.name}</div>
                  </td>
                  <td className="text-right font-semibold">{formatNumber(cdu.market_value, 0)}</td>
                  <td className="text-right">{formatNumber(cdu.daily_change, 0)}</td>
                  <td className="text-right">{formatPct(cdu.ytm_weighted)}</td>
                  <td className="text-right">{formatNumber(cdu.duration_weighted, 2)}</td>
                  <td className="max-w-[360px] truncate" title={cdu.latest_document ?? ''}>{cdu.latest_document ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detail.type === 'reports' && (
        <div className="space-y-4 p-4">
          <div className="flex flex-wrap gap-2">
            <button className="btn-secondary" disabled={!canExport || exporting} onClick={() => onExport('xlsx')}>
              <FileSpreadsheet className="h-4 w-4" />
              Сформировать XLSX
            </button>
            <button className="btn-secondary" disabled={!canExport || exporting} onClick={() => onExport('pdf')}>
              <FileText className="h-4 w-4" />
              Сформировать PDF
            </button>
            <Link to={`/reports?date=${date}`} className="btn-secondary">
              История отчётов
            </Link>
          </div>
          <div className="table-wrap rounded-xl border border-slate-200">
            <table className="kdif-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Тип</th>
                  <th>Версия</th>
                  <th>Статус</th>
                  <th>Создан</th>
                </tr>
              </thead>
              <tbody>
                {data.reports.map((report) => (
                  <tr key={report.id}>
                    <td>{report.id}</td>
                    <td>{reportTypeLabel(report.report_type)}</td>
                    <td>v{report.version}</td>
                    <td>{workflowStatusLabel(report.status)}</td>
                    <td>{formatDate(report.generated_at)}</td>
                  </tr>
                ))}
                {!data.reports.length && (
                  <tr>
                    <td colSpan={5} className="py-8 text-center text-slate-400">Отчётов за дату пока нет.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {detail.type === 'documents' && (
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>Файл</th>
                <th>Тип</th>
                <th>Статус</th>
                <th>Строк</th>
                <th>Загружен</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.id}>
                  <td className="max-w-[520px] truncate font-medium" title={doc.file_name}>{doc.file_name}</td>
                  <td>{documentTypeLabel(doc.doc_type)}</td>
                  <td>{processStatusLabel(doc.parse_status)}</td>
                  <td className="text-right">{formatNumber(doc.rows_imported, 0)}</td>
                  <td>{formatDate(doc.uploaded_at)}</td>
                </tr>
              ))}
              {!documents.length && (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-slate-400">Документов за выбранную дату нет.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function ActionRow({
  title,
  text,
  tone,
  to,
  onClick,
}: {
  title: string
  text: string
  tone: 'ok' | 'warn' | 'neutral'
  to?: string
  onClick?: () => void
}) {
  const Icon = tone === 'ok' ? CheckCircle2 : tone === 'warn' ? AlertTriangle : ArrowRight
  const color = tone === 'ok' ? 'text-emerald-700 bg-emerald-50' : tone === 'warn' ? 'text-amber-700 bg-amber-50' : 'text-slate-600 bg-slate-50'
  const content = (
    <div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 text-left transition hover:bg-slate-50">
      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${color}`}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="font-semibold text-slate-800">{title}</div>
        <div className="truncate text-xs text-slate-500" title={text}>{text}</div>
      </div>
      {(to || onClick) && <ArrowRight className="h-4 w-4 text-slate-400" />}
    </div>
  )
  if (to) return <Link to={to}>{content}</Link>
  if (onClick) return <button type="button" onClick={onClick} className="w-full">{content}</button>
  return content
}
