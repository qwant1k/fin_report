import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  FileSpreadsheet,
  FolderOpen,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Clock,
  ListTree,
  UploadCloud,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { formatDate } from '@/lib/format'

interface ImportJobItem {
  id: number
  job_type: string
  status: 'RUNNING' | 'DONE' | 'FAILED' | 'PARTIAL'
  triggered_by: string | null
  started_at: string | null
  finished_at: string | null
  files_total: number
  files_done: number
  files_failed: number
  rows_imported: number
}

interface ImportJobDetail extends ImportJobItem {
  log: string
  params: { folder?: string; pattern?: string } | null
}

const SUGGESTED_FOLDER =
  String.raw`e:\projects\Сиуа\KDIF_FIN\Примеры\Материалы от СИУА\Risk report`

const statusBadge = (s: ImportJobItem['status']) => {
  if (s === 'DONE')
    return (
      <span className="badge-ok">
        <CheckCircle2 className="w-3 h-3 inline mr-1" /> Готово
      </span>
    )
  if (s === 'PARTIAL')
    return (
      <span className="badge-warn">
        <CheckCircle2 className="w-3 h-3 inline mr-1" /> Частично
      </span>
    )
  if (s === 'FAILED')
    return (
      <span className="badge-breach">
        <XCircle className="w-3 h-3 inline mr-1" /> Ошибка
      </span>
    )
  return (
    <span className="badge-warn">
      <Clock className="w-3 h-3 inline mr-1 animate-pulse" /> Идёт
    </span>
  )
}

export default function ImportPage() {
  const qc = useQueryClient()
  const [folder, setFolder] = useState(SUGGESTED_FOLDER)
  const [pattern, setPattern] = useState('**/*.xlsm')
  const [password, setPassword] = useState('7')
  const [activeJobId, setActiveJobId] = useState<number | null>(null)
  const canRunImport = useAuthStore((s) => s.can('import.run'))

  // ───── Список последних job-ов ─────
  const jobs = useQuery<ImportJobItem[]>({
    queryKey: ['import-jobs'],
    queryFn: async () => (await api.get('/import/jobs', { params: { limit: 50 } })).data,
    refetchInterval: (q) => {
      // Если есть RUNNING — поллим каждые 3 сек, иначе 30
      const data = q.state.data as ImportJobItem[] | undefined
      const hasRunning = (data ?? []).some((j) => j.status === 'RUNNING')
      return hasRunning ? 3000 : 30_000
    },
  })

  // ───── Детали активного job-а ─────
  const jobDetail = useQuery<ImportJobDetail>({
    queryKey: ['import-job', activeJobId],
    queryFn: async () => (await api.get(`/import/jobs/${activeJobId}`)).data,
    enabled: !!activeJobId,
    refetchInterval: (q) => {
      const data = q.state.data as ImportJobDetail | undefined
      return data?.status === 'RUNNING' ? 2000 : false
    },
  })

  // ───── Single-file upload ─────
  const singleUpload = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('skip_if_imported', 'true')
      if (password.trim()) fd.append('password', password.trim())
      return (
        await api.post('/import/risk-report', fd, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
      ).data
    },
    onSuccess: (r) => {
      const total =
        Number(r.rows.cash) +
        Number(r.rows.mv) +
        Number(r.rows.bond_lots) +
        Number(r.rows.repo_lots) +
        Number(r.rows.deposit_lots) +
        Number(r.rows.accounts_receivable) +
        Number(r.rows.report_summaries ?? 0) +
        Number(r.rows.report_positions ?? 0)
      if (r.skipped) {
        toast.success(`Файл уже импортирован (${r.warnings?.[0] ?? 'дубликат'})`)
      } else {
        toast.success(
          `Импортировано: cash=${r.rows.cash} mv=${r.rows.mv} лоты=${r.rows.bond_lots} repo=${r.rows.repo_lots} dep=${r.rows.deposit_lots} ar=${r.rows.accounts_receivable} • всего: ${total}`,
        )
      }
      qc.invalidateQueries({ queryKey: ['import-jobs'] })
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Не удалось импортировать Risk Report')
    },
  })

  // ───── Bulk folder import ─────
  const bulkImport = useMutation({
    mutationFn: async () =>
      (await api.post('/import/risk-report/bulk-folder', {
        folder_path: folder,
        pattern,
        password: password.trim() || undefined,
      })).data,
    onSuccess: (r) => {
      toast.success(`Запущен job #${r.job_id} — папка: ${r.folder}`)
      setActiveJobId(r.job_id)
      qc.invalidateQueries({ queryKey: ['import-jobs'] })
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Не удалось запустить импорт Risk Report')
    },
  })

  const submitBulk = (e: FormEvent) => {
    e.preventDefault()
    if (!folder.trim()) {
      toast.error('Укажите путь к папке')
      return
    }
    bulkImport.mutate()
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Импорт исторических Risk Report</h1>
        <p className="text-sm text-slate-500">
          Загрузка XLSM-отчётов за прошлые периоды для построения истории и графиков
        </p>
      </header>

      {/* ───── Панель «Один файл» ───── */}
      {canRunImport && (
      <>
      <div className="card p-4">
        <h2 className="font-semibold mb-3 flex items-center gap-2">
          <FileSpreadsheet className="w-4 h-4 text-emerald-600" /> Загрузить один файл
        </h2>
        <div className="mb-3 max-w-sm">
          <label className="label">Пароль файла</label>
          <input
            className="input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="По умолчанию 7"
            autoComplete="off"
          />
        </div>
        <label
          htmlFor="rr-file"
          className="border-2 border-dashed border-slate-300 hover:border-kdif-green
                     rounded-lg p-8 text-center cursor-pointer block transition"
        >
          <UploadCloud className="w-8 h-8 mx-auto mb-2 text-slate-400" />
          <div className="font-medium">
            {singleUpload.isPending ? 'Импортируется…' : 'Кликните или перетащите .xlsm'}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            Поддерживается risk report_DDMMYYYY_.xlsm и .xlsx
          </div>
          <input
            id="rr-file"
            type="file"
            accept=".xlsm,.xlsx"
            className="hidden"
            disabled={singleUpload.isPending}
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) singleUpload.mutate(f)
              e.target.value = ''
            }}
          />
        </label>
      </div>

      {/* ───── Панель Bulk-import ───── */}
      <div className="card p-4">
        <h2 className="font-semibold mb-3 flex items-center gap-2">
          <FolderOpen className="w-4 h-4 text-emerald-600" /> Bulk-импорт из папки на сервере
        </h2>
        <form onSubmit={submitBulk} className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
          <div className="md:col-span-2">
            <label className="label">Абсолютный путь к папке</label>
            <input
              className="input"
              value={folder}
              onChange={(e) => setFolder(e.target.value)}
              placeholder={SUGGESTED_FOLDER}
            />
            <p className="text-xs text-slate-500 mt-1">
              Папка должна быть доступна на сервере; рекурсивный поиск по шаблону.
            </p>
          </div>
          <div>
            <label className="label">Шаблон</label>
            <input
              className="input"
              value={pattern}
              onChange={(e) => setPattern(e.target.value)}
              placeholder="**/*.xlsm"
            />
          </div>
          <div>
            <label className="label">Пароль файла</label>
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="По умолчанию 7"
              autoComplete="off"
            />
          </div>
          <div className="md:col-span-3 flex justify-end">
            <button
              type="submit"
              className="btn-primary"
              disabled={bulkImport.isPending}
            >
              <RefreshCw
                className={`w-4 h-4 ${bulkImport.isPending ? 'animate-spin' : ''}`}
              />{' '}
              {bulkImport.isPending ? 'Запускаем…' : 'Запустить bulk-импорт'}
            </button>
          </div>
        </form>
      </div>
      </>

      )}

      {/* ───── История запусков ───── */}
      <div className="card overflow-hidden">
        <div className="p-4 border-b border-slate-100 font-semibold flex items-center gap-2">
          <ListTree className="w-4 h-4" /> История импорта
          <button
            onClick={() => qc.invalidateQueries({ queryKey: ['import-jobs'] })}
            className="btn-secondary ml-auto text-xs"
          >
            <RefreshCw className="w-3 h-3" /> Обновить
          </button>
        </div>
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Тип</th>
                <th>Статус</th>
                <th>Файлы</th>
                <th>Строки</th>
                <th>Запущен</th>
                <th>Завершён</th>
                <th>Кем</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(jobs.data ?? []).map((j) => (
                <tr
                  key={j.id}
                  className={activeJobId === j.id ? 'bg-emerald-50/50' : ''}
                >
                  <td>#{j.id}</td>
                  <td>{j.job_type}</td>
                  <td>{statusBadge(j.status)}</td>
                  <td>
                    {j.files_done}/{j.files_total}
                    {j.files_failed > 0 && (
                      <span className="text-red-600 ml-1">({j.files_failed} ошибок)</span>
                    )}
                  </td>
                  <td>{j.rows_imported.toLocaleString('ru-RU')}</td>
                  <td>{formatDate(j.started_at)}</td>
                  <td>{formatDate(j.finished_at)}</td>
                  <td>{j.triggered_by ?? '—'}</td>
                  <td>
                    <button
                      onClick={() =>
                        setActiveJobId(activeJobId === j.id ? null : j.id)
                      }
                      className="btn-secondary text-xs"
                    >
                      {activeJobId === j.id ? 'Скрыть' : 'Лог'}
                    </button>
                  </td>
                </tr>
              ))}
              {!jobs.data?.length && (
                <tr>
                  <td colSpan={9} className="text-center text-slate-400 py-6">
                    Импортов пока не было
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ───── Лог детального job-а ───── */}
      {activeJobId && jobDetail.data && (
        <div className="card p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="font-semibold">
              Лог импорта #{jobDetail.data.id} — {statusBadge(jobDetail.data.status)}
            </div>
            <div className="text-xs text-slate-500">
              {jobDetail.data.params?.folder}
            </div>
          </div>

          {jobDetail.data.status === 'RUNNING' && (
            <div className="mb-3">
              <div className="flex justify-between text-xs text-slate-500 mb-1">
                <span>
                  Прогресс: {jobDetail.data.files_done} / {jobDetail.data.files_total}
                </span>
                <span>
                  {jobDetail.data.files_total > 0
                    ? Math.round(
                        (100 * jobDetail.data.files_done) /
                          jobDetail.data.files_total,
                      )
                    : 0}
                  %
                </span>
              </div>
              <div className="h-2 bg-slate-200 rounded overflow-hidden">
                <div
                  className="h-full bg-kdif-green transition-all"
                  style={{
                    width: `${
                      jobDetail.data.files_total > 0
                        ? (100 * jobDetail.data.files_done) /
                          jobDetail.data.files_total
                        : 0
                    }%`,
                  }}
                />
              </div>
            </div>
          )}

          <pre className="bg-slate-900 text-emerald-100 text-xs p-4 rounded overflow-auto max-h-96 whitespace-pre-wrap font-mono">
            {jobDetail.data.log || '(лог пуст)'}
          </pre>
        </div>
      )}
    </div>
  )
}
