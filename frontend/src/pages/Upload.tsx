import { useCallback, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AxiosError } from 'axios'
import {
  FileSpreadsheet,
  Trash2,
  UploadCloud,
  AlertCircle,
  CheckCircle2,
  FilePlus2,
  RefreshCw,
  Loader2,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { TradeFile, CDU } from '@/lib/types'
import { formatDate } from '@/lib/format'

type DuplicateAction = 'replace' | 'new_version'

interface DuplicateExisting {
  file_id: number
  filename: string
  uploaded_at: string | null
  uploaded_by: string | null
  cdu_id: number | null
  trade_date: string | null
  status: string
  rows_parsed: number
}

interface DuplicatePrompt {
  file: File
  existing: DuplicateExisting
}

type UploadPhase = 'uploading' | 'processing' | 'done' | 'failed' | 'duplicate'

interface UploadJob {
  id: string
  filename: string
  size: number
  phase: UploadPhase
  percent: number          // 0..100, byte-level for the upload phase
  message?: string
  rows?: number
  flagged?: number
  startedAt: number
  finishedAt?: number
}

async function postTradeReport(
  file: File,
  cduId: number | '',
  date: string,
  onDuplicate?: DuplicateAction,
  onUploadProgress?: (percent: number) => void,
) {
  const fd = new FormData()
  fd.append('file', file)
  if (cduId) fd.append('cdu_id', String(cduId))
  if (date) fd.append('trade_date', date)
  if (onDuplicate) fd.append('on_duplicate', onDuplicate)
  return (await api.post('/upload/trade-report', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (!onUploadProgress) return
      const total = e.total ?? file.size
      if (total > 0) {
        onUploadProgress(Math.min(100, Math.round((e.loaded / total) * 100)))
      }
    },
  })).data
}

export default function UploadPage() {
  const qc = useQueryClient()
  const [pendingCdu, setPendingCdu] = useState<number | ''>('')
  const [pendingDate, setPendingDate] = useState<string>('')
  const [duplicate, setDuplicate] = useState<DuplicatePrompt | null>(null)
  const [duplicateBusy, setDuplicateBusy] = useState<DuplicateAction | null>(null)
  const [jobs, setJobs] = useState<UploadJob[]>([])

  const updateJob = (id: string, patch: Partial<UploadJob>) =>
    setJobs((prev) => prev.map((j) => (j.id === id ? { ...j, ...patch } : j)))
  const removeJob = (id: string) => setJobs((prev) => prev.filter((j) => j.id !== id))

  const cdus = useQuery<CDU[]>({
    queryKey: ['cdus'],
    queryFn: async () => (await api.get('/settings/cdus')).data,
  })

  const files = useQuery<TradeFile[]>({
    queryKey: ['trade-files'],
    queryFn: async () => (await api.get('/upload/files')).data,
  })

  const handleUploadResult = (r: any, jobId?: string) => {
    toast.success(`${r.cdu_name ?? 'Файл'} • строк: ${r.rows_parsed}, пропущено: ${r.rows_skipped}`)
    const pc = r?.price_check
    if (pc) {
      if (pc.flagged > 0) {
        toast(
          `Расхождение с KASE: ${pc.flagged} из ${pc.checked} сделок заменены на цену KASE`,
          { icon: '⚑', duration: 6000 },
        )
      } else if (pc.checked > 0) {
        toast(`Сверка с KASE: ${pc.checked} сделок без расхождений`, { icon: '✓' })
      }
      if (pc.missing_kase > 0) {
        toast(`KASE-цена не найдена для ${pc.missing_kase} сделок`, { icon: 'ℹ️' })
      }
    }
    if (jobId) {
      updateJob(jobId, {
        phase: 'done',
        percent: 100,
        message: `${r.cdu_name ?? 'OK'} • ${r.rows_parsed} строк`,
        rows: r.rows_parsed,
        flagged: pc?.flagged ?? 0,
        finishedAt: Date.now(),
      })
      // Auto-remove successful jobs after a short delay so the user can see the result.
      setTimeout(() => removeJob(jobId), 5000)
    }
    qc.invalidateQueries({ queryKey: ['trade-files'] })
  }

  const uploadOne = async (file: File, jobId?: string) => {
    const id = jobId ?? `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    if (!jobId) {
      setJobs((prev) => [
        ...prev,
        {
          id,
          filename: file.name,
          size: file.size,
          phase: 'uploading',
          percent: 0,
          startedAt: Date.now(),
        },
      ])
    } else {
      updateJob(id, { phase: 'uploading', percent: 0, message: undefined })
    }
    try {
      const r = await postTradeReport(
        file, pendingCdu, pendingDate, undefined,
        (percent) => {
          updateJob(id, {
            percent,
            phase: percent >= 100 ? 'processing' : 'uploading',
            message: percent >= 100 ? 'Парсинг и импорт…' : `Передача ${percent}%`,
          })
        },
      )
      handleUploadResult(r, id)
    } catch (err) {
      const axErr = err as AxiosError<{ detail?: any }>
      const detail = axErr.response?.data?.detail
      if (axErr.response?.status === 409 && detail && typeof detail === 'object' && detail.error === 'duplicate_file') {
        setDuplicate({ file, existing: detail.existing as DuplicateExisting })
        updateJob(id, {
          phase: 'duplicate',
          message: 'Дубликат — выберите действие',
          finishedAt: Date.now(),
        })
        return
      }
      const message =
        (typeof detail === 'string' && detail) ||
        axErr.response?.statusText ||
        axErr.message ||
        'Ошибка загрузки'
      updateJob(id, { phase: 'failed', message, finishedAt: Date.now() })
      // other errors are already surfaced by the global interceptor
    }
  }

  const onDrop = useCallback((accepted: File[]) => {
    accepted.forEach((f) => { void uploadOne(f) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingCdu, pendingDate])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel.sheet.macroEnabled.12': ['.xlsm'],
    },
    multiple: true,
  })

  const resolveDuplicate = async (action: DuplicateAction) => {
    if (!duplicate) return
    setDuplicateBusy(action)
    // Find the in-flight job entry for this file (created in uploadOne) and
    // re-use it so the progress UI keeps a single row per file.
    const dupJob = jobs.find(
      (j) => j.filename === duplicate.file.name && j.phase === 'duplicate',
    )
    const jobId = dupJob?.id
    if (jobId) {
      updateJob(jobId, { phase: 'uploading', percent: 0, message: 'Повторная загрузка…' })
    }
    try {
      const r = await postTradeReport(
        duplicate.file, pendingCdu, pendingDate, action,
        jobId
          ? (percent) =>
              updateJob(jobId, {
                percent,
                phase: percent >= 100 ? 'processing' : 'uploading',
                message: percent >= 100 ? 'Парсинг и импорт…' : `Передача ${percent}%`,
              })
          : undefined,
      )
      handleUploadResult(r, jobId)
      setDuplicate(null)
    } catch (err) {
      if (jobId) {
        updateJob(jobId, {
          phase: 'failed',
          message: 'Не удалось обработать дубликат',
          finishedAt: Date.now(),
        })
      }
      toast.error('Не удалось обработать дубликат')
    } finally {
      setDuplicateBusy(null)
    }
  }

  const setCdu = useMutation({
    mutationFn: async ({ id, cduId }: { id: number; cduId: number }) =>
      (await api.put(`/upload/files/${id}/cdu`, null, { params: { cdu_id: cduId } })).data,
    onSuccess: () => {
      toast.success('ЧДУ обновлён')
      qc.invalidateQueries({ queryKey: ['trade-files'] })
    },
  })

  const remove = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/upload/files/${id}`)).data,
    onSuccess: () => {
      toast.success('Файл удалён')
      qc.invalidateQueries({ queryKey: ['trade-files'] })
    },
  })

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Загрузка отчётов от ЧДУ</h1>
        <p className="text-sm text-slate-500">XLSX выгрузка KASE-сделок (TradeReport)</p>
      </header>

      <div className="card p-4 space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="label">ЧДУ (опционально, иначе авто)</label>
            <select className="input" value={pendingCdu} onChange={(e) => setPendingCdu(e.target.value ? Number(e.target.value) : '')}>
              <option value="">Авто-определение</option>
              {cdus.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Дата торгов (опционально)</label>
            <input type="date" className="input" value={pendingDate} onChange={(e) => setPendingDate(e.target.value)} />
          </div>
        </div>
        <div
          {...getRootProps()}
          className={`border-2 border-dashed rounded-lg p-10 text-center cursor-pointer transition ${
            isDragActive ? 'border-kdif-green bg-emerald-50' : 'border-slate-300 hover:border-kdif-green'
          }`}
        >
          <input {...getInputProps()} />
          <UploadCloud className="w-10 h-10 mx-auto mb-2 text-slate-400" />
          <div className="font-medium">Перетащите XLSX/XLSM сюда или кликните для выбора</div>
          <div className="text-xs text-slate-500 mt-1">Можно загружать несколько файлов одновременно</div>
        </div>
      </div>

      {jobs.length > 0 && (
        <div className="card p-4 space-y-2">
          <div className="flex items-center justify-between">
            <div className="font-semibold">Текущие загрузки</div>
            <button
              type="button"
              onClick={() => setJobs((prev) => prev.filter((j) => j.phase !== 'done' && j.phase !== 'failed'))}
              className="text-xs text-slate-500 hover:text-slate-700"
            >
              Скрыть завершённые
            </button>
          </div>
          <div className="space-y-2">
            {jobs.map((job) => (
              <UploadJobCard key={job.id} job={job} onDismiss={() => removeJob(job.id)} />
            ))}
          </div>
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="p-4 border-b border-slate-100 font-semibold">История загрузок</div>
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Файл</th>
                <th>ЧДУ</th>
                <th>Дата торгов</th>
                <th>Загружено</th>
                <th>Кем</th>
                <th>Парсинг</th>
                <th>Статус</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(files.data ?? []).map((f) => (
                <tr key={f.id}>
                  <td>{f.id}</td>
                  <td className="flex items-center gap-2">
                    <FileSpreadsheet className="w-4 h-4 text-emerald-600" /> {f.filename}
                  </td>
                  <td>
                    <select
                      className="input py-1"
                      defaultValue={f.cdu_id ?? ''}
                      onChange={(e) => setCdu.mutate({ id: f.id, cduId: Number(e.target.value) })}
                    >
                      <option value="">— выбрать —</option>
                      {cdus.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                  </td>
                  <td>{formatDate(f.trade_date)}</td>
                  <td>{formatDate(f.uploaded_at)}</td>
                  <td className="text-xs text-slate-500">{f.uploaded_by ?? '—'}</td>
                  <td>{f.rows_parsed} / {f.rows_skipped}</td>
                  <td>
                    {f.status === 'PARSED' || f.status === 'IMPORTED'
                      ? <span className="badge-ok"><CheckCircle2 className="w-3 h-3 inline mr-1" />{f.status}</span>
                      : <span className="badge-warn"><AlertCircle className="w-3 h-3 inline mr-1" />{f.status}</span>}
                  </td>
                  <td>
                    <button onClick={() => remove.mutate(f.id)} className="btn-secondary text-red-600 px-2 py-1">
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
              {!files.data?.length && (
                <tr>
                  <td colSpan={9} className="text-center text-slate-400 py-6">Файлов пока нет</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {duplicate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="card w-full max-w-lg p-5 space-y-4 bg-white shadow-xl">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-6 h-6 text-amber-500 shrink-0 mt-0.5" />
              <div>
                <h2 className="text-lg font-semibold">Файл уже загружен</h2>
                <p className="text-sm text-slate-500 mt-1">
                  Контрольная сумма совпадает с существующим файлом. Выберите действие.
                </p>
              </div>
            </div>

            <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm space-y-1">
              <div><span className="text-slate-500">Файл:</span> <b>{duplicate.existing.filename}</b></div>
              <div><span className="text-slate-500">Дата торгов:</span> {duplicate.existing.trade_date ?? '—'}</div>
              <div><span className="text-slate-500">Загружено:</span> {formatDate(duplicate.existing.uploaded_at) || '—'}</div>
              <div><span className="text-slate-500">Кем:</span> {duplicate.existing.uploaded_by ?? '—'}</div>
              <div><span className="text-slate-500">Строк:</span> {duplicate.existing.rows_parsed}</div>
              <div><span className="text-slate-500">Статус:</span> {duplicate.existing.status}</div>
            </div>

            <div className="grid grid-cols-1 gap-2">
              <button
                disabled={!!duplicateBusy}
                onClick={() => resolveDuplicate('replace')}
                className="btn btn-primary justify-center"
              >
                <RefreshCw className="w-4 h-4" />
                {duplicateBusy === 'replace' ? 'Замена…' : 'Заменить существующий'}
              </button>
              <button
                disabled={!!duplicateBusy}
                onClick={() => resolveDuplicate('new_version')}
                className="btn btn-secondary justify-center"
              >
                <FilePlus2 className="w-4 h-4" />
                {duplicateBusy === 'new_version' ? 'Загрузка…' : 'Загрузить как новую версию'}
              </button>
              <button
                disabled={!!duplicateBusy}
                onClick={() => setDuplicate(null)}
                className="btn btn-secondary justify-center"
              >
                Отменить
              </button>
            </div>

            <p className="text-xs text-slate-500">
              «Заменить» — старый файл и связанные сделки переписываются. «Новая версия» — оба файла остаются в истории
              с разными отметками времени.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

// ─────────────── Upload progress card ───────────────

const PHASE_TEXT: Record<UploadPhase, string> = {
  uploading: 'Передача',
  processing: 'Обработка',
  done: 'Готово',
  failed: 'Ошибка',
  duplicate: 'Дубликат',
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function UploadJobCard({ job, onDismiss }: { job: UploadJob; onDismiss: () => void }) {
  const isActive = job.phase === 'uploading' || job.phase === 'processing'
  const barColor =
    job.phase === 'failed'
      ? 'bg-red-500'
      : job.phase === 'duplicate'
        ? 'bg-amber-500'
        : job.phase === 'done'
          ? 'bg-emerald-500'
          : 'bg-cyan-500'

  // For the processing phase, show an indeterminate-looking 100% bar.
  const widthPct = job.phase === 'processing' ? 100 : job.percent

  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="flex items-center gap-3">
        <FileSpreadsheet className="h-4 w-4 shrink-0 text-emerald-600" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <div className="truncate font-medium" title={job.filename}>{job.filename}</div>
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <span>{formatBytes(job.size)}</span>
              <span className="font-semibold uppercase tracking-wide">
                {PHASE_TEXT[job.phase]}
              </span>
              {!isActive && (
                <button
                  type="button"
                  onClick={onDismiss}
                  className="rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                  aria-label="Закрыть"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className={`h-full transition-[width] duration-200 ${barColor} ${
                job.phase === 'processing' ? 'animate-pulse' : ''
              }`}
              style={{ width: `${widthPct}%` }}
            />
          </div>
          <div className="mt-1 flex items-center justify-between gap-2 text-xs text-slate-500">
            <span className="truncate">
              {job.phase === 'failed' ? (
                <span className="text-red-600">{job.message ?? 'Ошибка'}</span>
              ) : job.phase === 'duplicate' ? (
                <span className="text-amber-600">{job.message ?? 'Дубликат файла'}</span>
              ) : job.phase === 'done' ? (
                <span className="text-emerald-700">{job.message ?? 'Готово'}</span>
              ) : (
                <span>{job.message ?? `${job.percent}%`}</span>
              )}
            </span>
            <span className="flex items-center gap-1 shrink-0">
              {job.phase === 'uploading' && <span>{job.percent}%</span>}
              {job.phase === 'processing' && <Loader2 className="h-3 w-3 animate-spin" />}
              {job.phase === 'done' && <CheckCircle2 className="h-3 w-3 text-emerald-600" />}
              {job.phase === 'failed' && <AlertCircle className="h-3 w-3 text-red-600" />}
              {job.phase === 'duplicate' && <FilePlus2 className="h-3 w-3 text-amber-600" />}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
