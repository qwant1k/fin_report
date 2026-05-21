import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2,
  Clock,
  Download,
  FileSpreadsheet,
  FileText,
  RefreshCw,
  Send,
  Trash2,
  XCircle,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
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
  const isAdmin = useAuthStore((s) => s.isAdmin())
  const canWrite = useAuthStore((s) => s.canWrite())
  const [searchParams, setSearchParams] = useSearchParams()
  const initialStatus = (searchParams.get('status') ?? '') as ReportStatus | ''
  const [statusFilter, setStatusFilter] = useState<ReportStatus | ''>(
    VALID_STATUSES.includes(initialStatus as ReportStatus) ? initialStatus : '',
  )
  const [rejectFor, setRejectFor] = useState<GeneratedReport | null>(null)
  const [rejectComment, setRejectComment] = useState('')

  // Keep URL in sync with the dropdown so deep links from the dashboard stick.
  useEffect(() => {
    const next = new URLSearchParams(searchParams)
    if (statusFilter) next.set('status', statusFilter)
    else next.delete('status')
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter])

  const reports = useQuery<GeneratedReport[]>({
    queryKey: ['reports', statusFilter],
    queryFn: async () => {
      const params: Record<string, string> = {}
      if (statusFilter) params.status = statusFilter
      return (await api.get('/reports/', { params })).data
    },
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['reports'] })

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

  const handleDownload = (id: number) => {
    window.open(`/api/reports/${id}/download`, '_blank')
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
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Сформированные отчёты</h1>
          <p className="text-sm text-slate-500">Утверждение и история версий</p>
        </div>
        <div className="flex items-center gap-2">
          <label className="label">Статус:</label>
          <select
            className="input"
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
      </header>

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
                    <div className="flex flex-wrap gap-1">
                      <button
                        className="btn-secondary px-2 py-1"
                        title="Скачать"
                        onClick={() => handleDownload(r.id)}
                      >
                        <Download className="w-4 h-4" />
                      </button>

                      {canWrite && (r.status === 'draft' || r.status === 'rejected') && (
                        <button
                          className="btn-primary px-2 py-1"
                          title="Отправить на утверждение"
                          onClick={() => submit.mutate(r.id)}
                          disabled={submit.isPending}
                        >
                          <Send className="w-4 h-4" />
                        </button>
                      )}

                      {canWrite && (r.status === 'draft' || r.status === 'rejected') && (
                        <button
                          className="btn-secondary px-2 py-1"
                          title="Перегенерировать"
                          onClick={() => regenerate.mutate(r.id)}
                          disabled={regenerate.isPending}
                        >
                          <RefreshCw className="w-4 h-4" />
                        </button>
                      )}

                      {isAdmin && r.status === 'pending_approval' && (
                        <>
                          <button
                            className="btn-primary px-2 py-1 bg-emerald-600 hover:bg-emerald-700"
                            title="Утвердить"
                            onClick={() => approve.mutate(r.id)}
                            disabled={approve.isPending}
                          >
                            <CheckCircle2 className="w-4 h-4" />
                          </button>
                          <button
                            className="btn-secondary px-2 py-1 text-red-700 border-red-300 hover:bg-red-50"
                            title="Отклонить"
                            onClick={() => { setRejectFor(r); setRejectComment('') }}
                          >
                            <XCircle className="w-4 h-4" />
                          </button>
                        </>
                      )}

                      {isAdmin && r.status !== 'approved' && (
                        <button
                          className="btn-secondary px-2 py-1 text-red-600"
                          title="Удалить"
                          onClick={() => remove.mutate(r.id)}
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={9} className="text-center text-slate-400 py-6">
                    Отчётов нет. Сгенерируйте через «Экспорт» на дашборде.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {rejectFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="card w-full max-w-lg p-5 space-y-4 bg-white shadow-xl">
            <div className="flex items-start gap-3">
              <XCircle className="w-6 h-6 text-red-600 shrink-0 mt-0.5" />
              <div>
                <h2 className="text-lg font-semibold">Отклонить отчёт #{rejectFor.id}</h2>
                <p className="text-sm text-slate-500 mt-1">
                  Укажите причину отклонения. Комментарий будет сохранён в аудит-логе.
                </p>
              </div>
            </div>
            <textarea
              className="input min-h-[100px]"
              placeholder="Например: расхождение по нормативу 12.04…"
              value={rejectComment}
              onChange={(e) => setRejectComment(e.target.value)}
              autoFocus
            />
            <div className="flex justify-end gap-2">
              <button
                className="btn btn-secondary"
                disabled={reject.isPending}
                onClick={() => { setRejectFor(null); setRejectComment('') }}
              >
                Отмена
              </button>
              <button
                className="btn btn-primary bg-red-600 hover:bg-red-700"
                disabled={reject.isPending || !rejectComment.trim()}
                onClick={confirmReject}
              >
                Отклонить
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
