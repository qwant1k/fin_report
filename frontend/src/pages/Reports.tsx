import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2,
  CalendarDays,
  Clock,
  Download,
  FileSpreadsheet,
  FileText,
  MoreHorizontal,
  RefreshCw,
  Send,
  Trash2,
  XCircle,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { Modal, PageHeader } from '@/components/ui'
import { downloadBlob, filenameFromPath } from '@/lib/download'
import { useAuthStore } from '@/lib/auth'
import { useConfirm } from '@/lib/confirm'
import { useWorkContextStore } from '@/lib/workContext'
import { formatDate } from '@/lib/format'
import { GeneratedReport, ReportStatus } from '@/lib/types'

const STATUS_LABEL: Record<ReportStatus, string> = {
  draft: 'Черновик',
  pending_approval: 'На утверждении',
  approved: 'Утверждён',
  rejected: 'Отклонён',
}

const STATUS_BADGE: Record<ReportStatus, string> = {
  draft: 'bg-slate-100 text-slate-700 border-slate-300',
  pending_approval: 'bg-amber-100 text-amber-800 border-amber-300',
  approved: 'bg-emerald-100 text-emerald-800 border-emerald-300',
  rejected: 'bg-red-100 text-red-800 border-red-300',
}

const STATUS_ICON: Record<ReportStatus, React.ReactNode> = {
  draft: <FileText className="w-3.5 h-3.5" />,
  pending_approval: <Clock className="w-3.5 h-3.5" />,
  approved: <CheckCircle2 className="w-3.5 h-3.5" />,
  rejected: <XCircle className="w-3.5 h-3.5" />,
}

const VALID_STATUSES: ReportStatus[] = ['draft', 'pending_approval', 'approved', 'rejected']

export default function ReportsPage() {
  const qc = useQueryClient()
  const can = useAuthStore((s) => s.can)
  const confirm = useConfirm()
  const [searchParams, setSearchParams] = useSearchParams()
  const initialStatus = (searchParams.get('status') ?? '') as ReportStatus | ''
  // Общая рабочая дата — синхронизирована с Рабочим днём, Позициями, KASE и Сверкой.
  const reportDate = useWorkContextStore((s) => s.workDate)
  const setReportDate = useWorkContextStore((s) => s.setWorkDate)
  const [statusFilter, setStatusFilter] = useState<ReportStatus | ''>(
    VALID_STATUSES.includes(initialStatus as ReportStatus) ? initialStatus : '',
  )
  const [openActionsId, setOpenActionsId] = useState<number | null>(null)
  const [rejectFor, setRejectFor] = useState<GeneratedReport | null>(null)
  const [rejectComment, setRejectComment] = useState('')

  // Deep link (например, из Рабочего дня: /reports?date=...) один раз при монтировании
  // подставляется в общий контекст даты, чтобы обе части приложения остались согласованы.
  useEffect(() => {
    const urlDate = searchParams.get('date')
    if (urlDate) setReportDate(urlDate)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Keep URL in sync with the dropdown so deep links from the dashboard stick.
  useEffect(() => {
    const next = new URLSearchParams(searchParams)
    if (statusFilter) next.set('status', statusFilter)
    else next.delete('status')
    if (reportDate) next.set('date', reportDate)
    else next.delete('date')
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportDate, statusFilter])

  const reports = useQuery<GeneratedReport[]>({
    queryKey: ['reports', statusFilter, reportDate],
    queryFn: async () => {
      const params: Record<string, string> = {}
      if (statusFilter) params.status = statusFilter
      if (reportDate) params.report_date = reportDate
      return (await api.get('/reports/', { params })).data
    },
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['reports'] })

  const generate = useMutation({
    mutationFn: async (type: 'xlsx' | 'pdf') => {
      const resp = await api.get(`/export/${type}`, {
        params: { report_date: reportDate },
        responseType: 'blob',
      })
      downloadBlob(resp.data, `risk_report_${reportDate.replaceAll('-', '')}.${type}`)
      return type
    },
    onSuccess: () => {
      toast.success('Отчёт сформирован')
      invalidate()
    },
  })

  const submit = useMutation({
    mutationFn: async (id: number) => (await api.post(`/reports/${id}/submit`)).data,
    onSuccess: () => { toast.success('Отправлено на утверждение'); invalidate() },
  })

  const approve = useMutation({
    mutationFn: async (id: number) => (await api.post(`/reports/${id}/approve`)).data,
    onSuccess: () => { toast.success('Отчёт утверждён'); invalidate() },
  })

  const reject = useMutation({
    mutationFn: async ({ id, comment }: { id: number; comment: string }) =>
      (await api.post(`/reports/${id}/reject`, { comment })).data,
    onSuccess: () => {
      toast.success('Отчёт отклонён')
      setRejectFor(null)
      setRejectComment('')
      invalidate()
    },
  })

  const regenerate = useMutation({
    mutationFn: async (id: number) => (await api.post(`/reports/${id}/regenerate`)).data,
    onSuccess: () => { toast.success('Отчёт перегенерирован'); invalidate() },
  })

  const remove = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/reports/${id}`)).data,
    onSuccess: () => { toast.success('Удалено'); invalidate() },
  })

  const handleDownload = async (report: GeneratedReport) => {
    const resp = await api.get(`/reports/${report.id}/download`, { responseType: 'blob' })
    downloadBlob(resp.data, filenameFromPath(report.file_path, `report_${report.id}`))
  }

  const reportLabel = (r: GeneratedReport) => `${r.report_type} v${r.version} от ${formatDate(r.report_date)}`

  const handleSubmit = async (r: GeneratedReport) => {
    const { confirmed } = await confirm({
      title: 'Отправить отчёт на утверждение?',
      description: `${reportLabel(r)} — после отправки отчёт увидит утверждающий и сможет одобрить или отклонить его.`,
      confirmLabel: 'Отправить',
    })
    if (confirmed) submit.mutate(r.id)
  }

  const handleApprove = async (r: GeneratedReport) => {
    const { confirmed } = await confirm({
      title: 'Утвердить отчёт?',
      description: `${reportLabel(r)} будет отмечен утверждённым и станет официальной версией за эту дату.`,
      confirmLabel: 'Утвердить',
    })
    if (confirmed) approve.mutate(r.id)
  }

  const handleRegenerate = async (r: GeneratedReport) => {
    const { confirmed } = await confirm({
      title: 'Перегенерировать отчёт?',
      description: `${reportLabel(r)} — текущий файл будет заменён на пересобранный из актуальных данных на дату отчёта.`,
      confirmLabel: 'Перегенерировать',
    })
    if (confirmed) regenerate.mutate(r.id)
  }

  const handleDelete = async (r: GeneratedReport) => {
    const { confirmed } = await confirm({
      title: 'Удалить отчёт?',
      description: `${reportLabel(r)} будет удалён безвозвратно, включая файл и историю версии.`,
      tone: 'danger',
      confirmLabel: 'Удалить',
    })
    if (confirmed) remove.mutate(r.id)
  }

  const confirmReject = () => {
    if (!rejectFor) return
    if (!rejectComment.trim()) {
      toast.error('Комментарий обязателен')
      return
    }
    reject.mutate({ id: rejectFor.id, comment: rejectComment.trim() })
  }

  const rows = reports.data ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        icon={FileText}
        title="Сформированные отчёты"
        subtitle="Утверждение и история версий"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <CalendarDays className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                type="date"
                className="input h-10 w-44 pl-9"
                value={reportDate}
                onChange={(e) => setReportDate(e.target.value)}
              />
            </div>
            {can('reports.export') && (
              <>
                <button className="btn-secondary h-10" disabled={generate.isPending || !reportDate} onClick={() => generate.mutate('xlsx')}>
                  <FileSpreadsheet className="h-4 w-4" />
                  XLSX
                </button>
                <button className="btn-secondary h-10" disabled={generate.isPending || !reportDate} onClick={() => generate.mutate('pdf')}>
                  <FileText className="h-4 w-4" />
                  PDF
                </button>
              </>
            )}
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Статус:</span>
            <select
              className="input h-10 w-48"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as ReportStatus | '')}
            >
              <option value="">Все</option>
              <option value="draft">{STATUS_LABEL.draft}</option>
              <option value="pending_approval">{STATUS_LABEL.pending_approval}</option>
              <option value="approved">{STATUS_LABEL.approved}</option>
              <option value="rejected">{STATUS_LABEL.rejected}</option>
            </select>
          </div>
        }
      />

      <div className="card overflow-hidden">
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Дата</th>
                <th>Тип</th>
                <th>Версия</th>
                <th>Статус</th>
                <th>Создан</th>
                <th>На утверждение</th>
                <th>Решение</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.id}</td>
                  <td>{r.report_date}</td>
                  <td className="flex items-center gap-1">
                    {r.report_type.includes('PDF')
                      ? <FileText className="w-4 h-4 text-red-500" />
                      : <FileSpreadsheet className="w-4 h-4 text-emerald-600" />}
                    {r.report_type}
                  </td>
                  <td>v{r.version}</td>
                  <td>
                    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[r.status]}`}>
                      {STATUS_ICON[r.status]}{STATUS_LABEL[r.status]}
                    </span>
                  </td>
                  <td className="text-xs">
                    <div>{formatDate(r.generated_at)}</div>
                    <div className="text-slate-500">{r.generated_by ?? '—'}</div>
                  </td>
                  <td className="text-xs">
                    {r.submitted_at ? (
                      <>
                        <div>{formatDate(r.submitted_at)}</div>
                        <div className="text-slate-500">{r.submitted_by ?? '—'}</div>
                      </>
                    ) : '—'}
                  </td>
                  <td className="text-xs">
                    {r.status === 'approved' && (
                      <>
                        <div>{formatDate(r.approved_at)}</div>
                        <div className="text-slate-500">{r.approved_by ?? '—'}</div>
                      </>
                    )}
                    {r.status === 'rejected' && (
                      <>
                        <div>{formatDate(r.rejected_at)}</div>
                        <div className="text-slate-500">{r.rejected_by ?? '—'}</div>
                        {r.rejection_comment && (
                          <div className="text-red-700 mt-0.5" title={r.rejection_comment}>
                            «{r.rejection_comment.slice(0, 60)}{r.rejection_comment.length > 60 ? '…' : ''}»
                          </div>
                        )}
                      </>
                    )}
                    {(r.status === 'draft' || r.status === 'pending_approval') && '—'}
                  </td>
                  <td>
                    {(() => {
                      const canSubmitReport = can('reports.submit') && (r.status === 'draft' || r.status === 'rejected')
                      const canRegenerateReport = can('reports.regenerate') && (r.status === 'draft' || r.status === 'rejected')
                      const canDeleteReport = can('reports.delete') && r.status !== 'approved'
                      const hasMoreActions = canRegenerateReport || canDeleteReport

                      return (
                        <div className="flex items-center justify-end gap-1">
                          <button
                            className="btn-secondary px-2 py-1"
                            title="Скачать"
                            aria-label="Скачать"
                            onClick={() => { void handleDownload(r) }}
                          >
                            <Download className="w-4 h-4" />
                          </button>

                          {canSubmitReport && (
                            <button
                              className="btn-primary px-2 py-1"
                              title="Отправить на утверждение"
                              aria-label="Отправить на утверждение"
                              onClick={() => handleSubmit(r)}
                              disabled={submit.isPending}
                            >
                              <Send className="w-4 h-4" />
                            </button>
                          )}

                          {(can('reports.approve') || can('reports.reject')) && r.status === 'pending_approval' && (
                            <>
                              {can('reports.approve') && (
                                <button
                                  className="btn-primary bg-emerald-600 px-2 py-1 hover:bg-emerald-700"
                                  title="Утвердить"
                                  aria-label="Утвердить"
                                  onClick={() => handleApprove(r)}
                                  disabled={approve.isPending}
                                >
                                  <CheckCircle2 className="w-4 h-4" />
                                </button>
                              )}
                              {can('reports.reject') && (
                                <button
                                  className="btn-secondary border-red-300 px-2 py-1 text-red-700 hover:bg-red-50"
                                  title="Отклонить"
                                  aria-label="Отклонить"
                                  onClick={() => { setRejectFor(r); setRejectComment(''); setOpenActionsId(null) }}
                                >
                                  <XCircle className="w-4 h-4" />
                                </button>
                              )}
                            </>
                          )}

                          {hasMoreActions && (
                            <div className="relative">
                              <button
                                type="button"
                                className="btn-secondary px-2 py-1"
                                title="Еще действия"
                                aria-label="Еще действия"
                                aria-expanded={openActionsId === r.id}
                                onClick={() => setOpenActionsId((id) => (id === r.id ? null : r.id))}
                              >
                                <MoreHorizontal className="w-4 h-4" />
                              </button>
                              {openActionsId === r.id && (
                                <div className="absolute right-0 z-30 mt-2 w-52 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 text-left shadow-card">
                                  {canRegenerateReport && (
                                    <button
                                      type="button"
                                      className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-emerald-50 hover:text-emerald-800"
                                      onClick={() => {
                                        setOpenActionsId(null)
                                        handleRegenerate(r)
                                      }}
                                      disabled={regenerate.isPending}
                                    >
                                      <RefreshCw className="h-4 w-4" />
                                      Перегенерировать
                                    </button>
                                  )}
                                  {canDeleteReport && (
                                    <button
                                      type="button"
                                      className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50"
                                      onClick={() => {
                                        setOpenActionsId(null)
                                        handleDelete(r)
                                      }}
                                    >
                                      <Trash2 className="h-4 w-4" />
                                      Удалить
                                    </button>
                                  )}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      )
                    })()}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={9} className="py-10 text-center text-slate-400">
                    Отчётов нет. Сгенерируйте через «Экспорт» на дашборде.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <Modal
        open={!!rejectFor}
        onClose={() => { if (!reject.isPending) { setRejectFor(null); setRejectComment('') } }}
        title={
          <span className="flex items-center gap-2">
            <XCircle className="h-5 w-5 text-red-600" /> Отклонить отчёт{rejectFor ? ` #${rejectFor.id}` : ''}
          </span>
        }
        description="Укажите причину отклонения. Комментарий будет сохранён в аудит-логе."
        footer={
          <>
            <button
              className="btn-secondary"
              disabled={reject.isPending}
              onClick={() => { setRejectFor(null); setRejectComment('') }}
            >
              Отмена
            </button>
            <button className="btn-danger" disabled={reject.isPending || !rejectComment.trim()} onClick={confirmReject}>
              Отклонить
            </button>
          </>
        }
      >
        <textarea
          className="input min-h-[120px]"
          placeholder="Например: расхождение по нормативу 12.04…"
          value={rejectComment}
          onChange={(e) => setRejectComment(e.target.value)}
          autoFocus
        />
      </Modal>
    </div>
  )
}
