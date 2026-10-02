import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { useDropzone } from 'react-dropzone'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AxiosError } from 'axios'
import {
  AlertCircle,
  Building2,
  CheckCircle2,
  Clock,
  FilePlus2,
  FileSpreadsheet,
  FileText,
  Loader2,
  RefreshCw,
  Trash2,
  UploadCloud,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { Modal, PageHeader, Segmented } from '@/components/ui'
import { useAuthStore } from '@/lib/auth'
import { useConfirm } from '@/lib/confirm'
import { useWorkContextStore } from '@/lib/workContext'
import { CDU, TradeFile } from '@/lib/types'
import { formatDate } from '@/lib/format'

// ─────────────────────────── маршрутизация файлов ───────────────────────────
// В системе два независимых загрузчика:
//  - /upload/trade-report — специализированный: проверка цен KASE, авто-ЧДУ,
//    явная обработка дублей. Клиент явно указывает, что это Trade Report.
//  - /primary-data/upload — общий импортёр Holdings/Сверки/Биржевых свидетельств/
//    Выписок. Он САМ определяет подтип по названию файла на сервере — клиент
//    не может выбрать конкретный подтип, поэтому мы не показываем это как
//    редактируемый выбор (это было бы обманом: выбор ничего не меняет).
type UploadRoute = 'trade_report' | 'primary'

// Тот же эвристический guess, что использует backend (_detect_file_type в
// primary_data_routes.py) — только для превью пользователю, не для реальной
// классификации: окончательное решение всегда принимает сервер.
type GuessedType = 'trade_report' | 'holdings' | 'reconciliation' | 'exchange_certificate' | 'pdf_statement' | 'unknown'

const GUESS_LABEL: Record<GuessedType, string> = {
  trade_report: 'Trade Report',
  holdings: 'Holdings',
  reconciliation: 'Сверка',
  exchange_certificate: 'Биржевое свидетельство',
  pdf_statement: 'Выписка PDF',
  unknown: 'не определён — сервер может отклонить файл',
}

function guessType(filename: string): GuessedType {
  const f = filename.toLowerCase()
  if (/\.(xlsx|xlsm)$/.test(f) && (f.includes('trade report') || f.includes('trade_report') || f.includes('сделки') || f.includes('trade'))) {
    return 'trade_report'
  }
  if (f.endsWith('.xlsx') && (f.includes('holdings') || f.includes('позиции') || f.includes('активах'))) return 'holdings'
  if (f.endsWith('.xlsx') && (f.includes('сверка') || f.includes('recon'))) return 'reconciliation'
  if (/\.(pdf|png|jpe?g|docx)$/.test(f) && (f.includes('биржев') || f.includes('certificate') || f.includes('cert'))) return 'exchange_certificate'
  if (f.endsWith('.pdf') && (f.includes('выписка') || f.includes('statement'))) return 'pdf_statement'
  if (/\.(xlsx|xlsm)$/.test(f)) return 'trade_report'
  return 'unknown'
}

// Реальные коды типа документа, которые хранит backend (см. Workday.tsx DOC_LABEL
// и api/routes/primary_data_routes.py::_to_doc_type) — используются в истории загрузок.
const BACKEND_DOC_LABEL: Record<string, string> = {
  TRADE_REPORT: 'Trade Report',
  HOLDINGS: 'Holdings',
  RECONCILIATION: 'Сверка',
  CERTIFICATE: 'Биржевое свидетельство',
  STATEMENT_PDF: 'Выписка PDF',
  RISK_REPORT_XLSM: 'Risk Report',
  OTHER: 'Прочее',
}

const BACKEND_DOC_ICON: Record<string, ReactNode> = {
  TRADE_REPORT: <FileSpreadsheet className="h-4 w-4 text-emerald-600" />,
  HOLDINGS: <FileSpreadsheet className="h-4 w-4 text-sky-600" />,
  RECONCILIATION: <FileText className="h-4 w-4 text-amber-600" />,
  CERTIFICATE: <FileText className="h-4 w-4 text-violet-600" />,
  STATEMENT_PDF: <FileText className="h-4 w-4 text-red-600" />,
  RISK_REPORT_XLSM: <FileText className="h-4 w-4 text-emerald-600" />,
}

type QueueStatus = 'queued' | 'uploading' | 'done' | 'error' | 'duplicate'

interface QueueItem {
  id: string
  file: File
  guess: GuessedType
  route: UploadRoute
  cduId: number | ''
  tradeDate: string
  status: QueueStatus
  message?: string
}

interface DuplicateExisting {
  file_id: number
  filename: string
  uploaded_at: string | null
  uploaded_by: string | null
  trade_date: string | null
  status: string
  rows_parsed: number
}

interface SourceDoc {
  id: number
  filename: string
  file_type: string
  file_size: number
  import_status: string
  imported_at: string
  imported_by: string | null
  source_cdu: string | null
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export default function DocumentsPage() {
  const qc = useQueryClient()
  const confirm = useConfirm()
  const workDate = useWorkContextStore((s) => s.workDate)
  const canTradeReport = useAuthStore((s) => s.can('upload.trade_report'))
  const canPrimary = useAuthStore((s) => s.can('primary_data.upload'))
  const canUploadAny = canTradeReport || canPrimary

  const [queue, setQueue] = useState<QueueItem[]>([])
  const [historyTab, setHistoryTab] = useState<'trade_report' | 'primary'>('trade_report')
  const [duplicate, setDuplicate] = useState<{ item: QueueItem; existing: DuplicateExisting } | null>(null)
  const [duplicateBusy, setDuplicateBusy] = useState<'replace' | 'new_version' | null>(null)

  const cdus = useQuery<CDU[]>({
    queryKey: ['cdus'],
    queryFn: async () => (await api.get('/settings/cdus')).data,
  })

  const tradeFiles = useQuery<TradeFile[]>({
    queryKey: ['trade-files'],
    queryFn: async () => (await api.get('/upload/files')).data,
    enabled: historyTab === 'trade_report',
  })

  const primaryDocs = useQuery<SourceDoc[]>({
    queryKey: ['primary-documents'],
    queryFn: async () => (await api.get('/primary-data/documents?limit=50')).data,
    enabled: historyTab === 'primary',
  })

  const updateItem = (id: string, patch: Partial<QueueItem>) =>
    setQueue((prev) => prev.map((it) => (it.id === id ? { ...it, ...patch } : it)))
  const removeItem = (id: string) => setQueue((prev) => prev.filter((it) => it.id !== id))

  const onDrop = useCallback(
    (accepted: File[]) => {
      const items: QueueItem[] = accepted.map((file) => {
        const guess = guessType(file.name)
        return {
          id: `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          file,
          guess,
          route: guess === 'trade_report' ? 'trade_report' : 'primary',
          cduId: '',
          tradeDate: workDate,
          status: 'queued',
        }
      })
      setQueue((prev) => [...prev, ...items])
    },
    [workDate],
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: true,
    disabled: !canUploadAny,
  })

  const uploadTradeReport = async (item: QueueItem, onDuplicate?: 'replace' | 'new_version') => {
    const fd = new FormData()
    fd.append('file', item.file)
    if (item.cduId) fd.append('cdu_id', String(item.cduId))
    if (item.tradeDate) fd.append('trade_date', item.tradeDate)
    if (onDuplicate) fd.append('on_duplicate', onDuplicate)
    return (await api.post('/upload/trade-report', fd, { headers: { 'Content-Type': 'multipart/form-data' } })).data
  }

  const uploadPrimary = async (item: QueueItem) => {
    const fd = new FormData()
    fd.append('file', item.file)
    return (await api.post('/primary-data/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } })).data
  }

  const processItem = async (item: QueueItem, onDuplicate?: 'replace' | 'new_version') => {
    updateItem(item.id, { status: 'uploading', message: undefined })
    try {
      if (item.route === 'trade_report') {
        const r = await uploadTradeReport(item, onDuplicate)
        const pc = r?.price_check
        toast.success(`${r.cdu_name ?? item.file.name} • строк: ${r.rows_parsed}, пропущено: ${r.rows_skipped}`)
        if (pc?.flagged > 0) {
          toast(`Расхождение с KASE: ${pc.flagged} из ${pc.checked} сделок заменены на цену KASE`, { icon: '⚑', duration: 6000 })
        }
        updateItem(item.id, { status: 'done', message: `${r.rows_parsed} строк импортировано` })
        qc.invalidateQueries({ queryKey: ['trade-files'] })
      } else {
        const r = await uploadPrimary(item)
        // Важно: при ошибке импорта backend отвечает HTTP 200 с status="FAILED" в теле
        // (см. api/routes/primary_data_routes.py), а не HTTP-ошибкой — если не проверить
        // это явно, неудачный импорт выглядел бы как успешный.
        if (r.status === 'FAILED') {
          toast.error(r.message ?? 'Импорт не выполнен')
          updateItem(item.id, { status: 'error', message: r.message ?? 'Импорт не выполнен' })
        } else if (r.status === 'SKIPPED') {
          toast('Пропущено — файл уже был импортирован ранее', { icon: 'ℹ️' })
          updateItem(item.id, { status: 'done', message: 'Пропущено (дубликат)' })
        } else {
          toast.success('Импорт завершён')
          updateItem(item.id, { status: 'done', message: r.message ?? 'Импортировано' })
        }
        qc.invalidateQueries({ queryKey: ['primary-documents'] })
      }
    } catch (err) {
      const axErr = err as AxiosError<{ detail?: any }>
      const detail = axErr.response?.data?.detail
      if (item.route === 'trade_report' && axErr.response?.status === 409 && detail?.error === 'duplicate_file') {
        setDuplicate({ item, existing: detail.existing as DuplicateExisting })
        updateItem(item.id, { status: 'duplicate', message: 'Дубликат — выберите действие' })
        return
      }
      const message = (typeof detail === 'string' && detail) || axErr.message || 'Ошибка импорта'
      updateItem(item.id, { status: 'error', message })
    }
  }

  const importAll = async () => {
    const pending = queue.filter((it) => it.status === 'queued' || it.status === 'error')
    for (const item of pending) {
      // Загружаем последовательно — так проще читать статус каждого файла и не перегружать сервер.
      await processItem(item)
    }
  }

  const resolveDuplicate = async (action: 'replace' | 'new_version') => {
    if (!duplicate) return
    setDuplicateBusy(action)
    try {
      await processItem(duplicate.item, action)
      setDuplicate(null)
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

  const removeTradeFile = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/upload/files/${id}`)).data,
    onSuccess: () => {
      toast.success('Файл удалён')
      qc.invalidateQueries({ queryKey: ['trade-files'] })
    },
  })

  const queuedCount = useMemo(() => queue.filter((it) => it.status === 'queued' || it.status === 'error').length, [queue])

  return (
    <div className="space-y-6">
      <PageHeader
        icon={UploadCloud}
        title="Загрузка документов"
        subtitle="Trade Report и первичные документы ЧДУ — в одном месте, с проверкой перед импортом"
      />

      {canUploadAny && (
        <div className="card space-y-4 p-4">
          <div
            {...getRootProps()}
            className={cn(
              'group relative cursor-pointer overflow-hidden rounded-2xl border-2 border-dashed p-10 text-center transition-colors duration-200',
              isDragActive ? 'border-emerald-500 bg-emerald-50/80 ring-4 ring-emerald-500/10' : 'border-slate-300 hover:border-emerald-400 hover:bg-emerald-50/40',
            )}
          >
            <input {...getInputProps()} />
            <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-gradient text-white shadow-soft">
              <UploadCloud className="h-8 w-8" />
            </div>
            <div className="font-semibold text-slate-800">
              {isDragActive ? 'Отпустите файлы для добавления в очередь' : 'Перетащите файлы сюда или кликните'}
            </div>
            <div className="mt-1 text-xs text-slate-500">
              Trade Report, Holdings, Сверка, Биржевые свидетельства, Выписки PDF — можно вперемешку
            </div>
            <div className="mt-3 flex items-center justify-center gap-2">
              <span className="badge-neutral">.xlsx</span>
              <span className="badge-neutral">.xlsm</span>
              <span className="badge-neutral">.pdf</span>
              <span className="badge-neutral">.docx</span>
              <span className="badge-neutral">.png</span>
            </div>
          </div>
          <p className="flex items-start gap-1.5 text-xs text-slate-500">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
            Ничего не загружается сразу после выбора файла. Trade Report обрабатывается отдельно (проверка ЧДУ, даты
            и цен KASE) — остальные документы система классифицирует сама по содержимому при импорте; ниже показан
            только предварительный ориентир по названию файла.
          </p>
        </div>
      )}

      {queue.length > 0 && (
        <div className="card overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-4">
            <div>
              <h2 className="section-title">Очередь на импорт</h2>
              <p className="text-sm text-slate-500">Проверьте маршрут обработки, ЧДУ и дату перед загрузкой</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setQueue((prev) => prev.filter((it) => it.status !== 'done'))}
                className="btn-ghost h-9 px-3 text-xs"
              >
                Скрыть завершённые
              </button>
              <button
                type="button"
                onClick={importAll}
                disabled={queuedCount === 0}
                className="btn-primary h-9 px-4 text-sm"
              >
                <UploadCloud className="h-4 w-4" />
                Импортировать{queuedCount > 0 ? ` (${queuedCount})` : ''}
              </button>
            </div>
          </div>

          <div className="divide-y divide-slate-100">
            {queue.map((item) => (
              <QueueRow
                key={item.id}
                item={item}
                cdus={cdus.data ?? []}
                onChangeRoute={(route) => updateItem(item.id, { route })}
                onChangeCdu={(cduId) => updateItem(item.id, { cduId })}
                onChangeDate={(tradeDate) => updateItem(item.id, { tradeDate })}
                onImport={() => processItem(item)}
                onRemove={() => removeItem(item.id)}
              />
            ))}
          </div>
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-4">
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-slate-400" />
            <h2 className="section-title">История загрузок</h2>
          </div>
          <div className="flex items-center gap-2">
            <Segmented
              layoutId="documents-history-tab"
              size="sm"
              value={historyTab}
              onChange={setHistoryTab}
              options={[
                { value: 'trade_report', label: 'Trade Report' },
                { value: 'primary', label: 'Первичные документы' },
              ]}
            />
            <button
              type="button"
              onClick={() => (historyTab === 'trade_report' ? tradeFiles.refetch() : primaryDocs.refetch())}
              className="btn-secondary h-9 px-3 text-xs"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', (tradeFiles.isFetching || primaryDocs.isFetching) && 'animate-spin')} />
              Обновить
            </button>
          </div>
        </div>

        {historyTab === 'trade_report' ? (
          <div className="table-wrap">
            <table className="kdif-table">
              <thead>
                <tr>
                  <th>Файл</th>
                  <th>ЧДУ</th>
                  <th>Дата торгов</th>
                  <th>Загружено</th>
                  <th>Парсинг</th>
                  <th>Статус</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {(tradeFiles.data ?? []).map((f) => (
                  <tr key={f.id} className="group">
                    <td className="flex items-center gap-2">
                      <FileSpreadsheet className="h-4 w-4 text-emerald-600" /> {f.filename}
                    </td>
                    <td>
                      <select
                        className="input py-1"
                        defaultValue={f.cdu_id ?? ''}
                        onChange={(e) => setCdu.mutate({ id: f.id, cduId: Number(e.target.value) })}
                        disabled={!canTradeReport}
                      >
                        <option value="">— выбрать —</option>
                        {cdus.data?.map((c) => (
                          <option key={c.id} value={c.id}>{c.name}</option>
                        ))}
                      </select>
                    </td>
                    <td>{formatDate(f.trade_date)}</td>
                    <td>{formatDate(f.uploaded_at)}</td>
                    <td>{f.rows_parsed} / {f.rows_skipped}</td>
                    <td>
                      {f.status === 'PARSED' || f.status === 'IMPORTED' ? (
                        <span className="badge-ok"><CheckCircle2 className="mr-1 inline h-3 w-3" />{f.status}</span>
                      ) : (
                        <span className="badge-warn"><AlertCircle className="mr-1 inline h-3 w-3" />{f.status}</span>
                      )}
                    </td>
                    <td>
                      {canTradeReport && (
                        <button
                          onClick={async () => {
                            const { confirmed } = await confirm({
                              title: 'Удалить файл Trade Report?',
                              description: `«${f.filename}» и связанные с ним сделки будут удалены безвозвратно.`,
                              tone: 'danger',
                              confirmLabel: 'Удалить',
                            })
                            if (confirmed) removeTradeFile.mutate(f.id)
                          }}
                          className="btn-secondary px-2 py-1 text-red-600 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:focus:opacity-100"
                          title="Удалить файл"
                          aria-label="Удалить файл"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {!tradeFiles.data?.length && (
                  <tr>
                    <td colSpan={7} className="py-10 text-center text-slate-400">Файлов пока нет</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="kdif-table">
              <thead>
                <tr>
                  <th>Файл</th>
                  <th>Тип</th>
                  <th>Статус</th>
                  <th>ЧДУ</th>
                  <th>Размер</th>
                  <th>Загружен</th>
                </tr>
              </thead>
              <tbody>
                {(primaryDocs.data ?? []).map((d) => (
                  <tr key={d.id}>
                    <td className="max-w-[280px] truncate font-medium" title={d.filename}>{d.filename}</td>
                    <td>
                      <span className="inline-flex items-center gap-1.5 text-xs text-slate-600">
                        {BACKEND_DOC_ICON[d.file_type] ?? <FileText className="h-4 w-4 text-slate-400" />}
                        {BACKEND_DOC_LABEL[d.file_type] ?? d.file_type}
                      </span>
                    </td>
                    <td>
                      <span className={cn('badge', d.import_status === 'OK' ? 'badge-ok' : d.import_status === 'ERROR' ? 'badge-breach' : 'badge-warn')}>
                        {d.import_status}
                      </span>
                    </td>
                    <td>
                      {d.source_cdu ? (
                        <span className="flex items-center gap-1 text-xs"><Building2 className="h-3 w-3" />{d.source_cdu}</span>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="text-right text-xs text-slate-500">{formatBytes(d.file_size)}</td>
                    <td className="text-xs text-slate-500">{formatDate(d.imported_at)}</td>
                  </tr>
                ))}
                {!primaryDocs.data?.length && (
                  <tr>
                    <td colSpan={6} className="py-10 text-center text-slate-400">Документов пока нет</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <Modal
        open={!!duplicate}
        onClose={() => { if (!duplicateBusy) setDuplicate(null) }}
        size="lg"
        title={
          <span className="flex items-center gap-2">
            <AlertCircle className="h-5 w-5 text-amber-500" /> Файл уже загружен
          </span>
        }
        description="Контрольная сумма совпадает с существующим файлом. Выберите действие."
        footer={
          <button disabled={!!duplicateBusy} onClick={() => setDuplicate(null)} className="btn-secondary">
            Отменить
          </button>
        }
      >
        {duplicate && (
          <div className="space-y-4">
            <div className="space-y-1 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
              <div><span className="text-slate-500">Файл:</span> <b>{duplicate.existing.filename}</b></div>
              <div><span className="text-slate-500">Дата торгов:</span> {duplicate.existing.trade_date ?? '—'}</div>
              <div><span className="text-slate-500">Загружено:</span> {formatDate(duplicate.existing.uploaded_at) || '—'}</div>
              <div><span className="text-slate-500">Кем:</span> {duplicate.existing.uploaded_by ?? '—'}</div>
              <div><span className="text-slate-500">Строк:</span> {duplicate.existing.rows_parsed}</div>
              <div><span className="text-slate-500">Статус:</span> {duplicate.existing.status}</div>
            </div>
            <div className="grid grid-cols-1 gap-2">
              <button disabled={!!duplicateBusy} onClick={() => resolveDuplicate('replace')} className="btn-primary justify-center">
                <RefreshCw className="h-4 w-4" />
                {duplicateBusy === 'replace' ? 'Замена…' : 'Заменить существующий'}
              </button>
              <button disabled={!!duplicateBusy} onClick={() => resolveDuplicate('new_version')} className="btn-secondary justify-center">
                <FilePlus2 className="h-4 w-4" />
                {duplicateBusy === 'new_version' ? 'Загрузка…' : 'Загрузить как новую версию'}
              </button>
            </div>
            <p className="text-xs text-slate-500">
              «Заменить» — старый файл и связанные сделки переписываются. «Новая версия» — оба файла остаются в истории.
            </p>
          </div>
        )}
      </Modal>
    </div>
  )
}

// ─────────────────────────── строка очереди ───────────────────────────

const STATUS_BADGE: Record<QueueStatus, string> = {
  queued: 'badge-neutral',
  uploading: 'badge-info',
  done: 'badge-ok',
  error: 'badge-breach',
  duplicate: 'badge-warn',
}

const STATUS_LABEL: Record<QueueStatus, string> = {
  queued: 'В очереди',
  uploading: 'Загрузка…',
  done: 'Готово',
  error: 'Ошибка',
  duplicate: 'Дубликат',
}

function QueueRow({
  item,
  cdus,
  onChangeRoute,
  onChangeCdu,
  onChangeDate,
  onImport,
  onRemove,
}: {
  item: QueueItem
  cdus: CDU[]
  onChangeRoute: (r: UploadRoute) => void
  onChangeCdu: (id: number | '') => void
  onChangeDate: (d: string) => void
  onImport: () => void
  onRemove: () => void
}) {
  const busy = item.status === 'uploading'
  const isTradeReport = item.route === 'trade_report'
  const locked = busy || item.status === 'done'

  return (
    <div className="flex flex-wrap items-center gap-3 p-3">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100">
        {isTradeReport ? <FileSpreadsheet className="h-4 w-4 text-emerald-600" /> : <FileText className="h-4 w-4 text-slate-500" />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-slate-800" title={item.file.name}>{item.file.name}</div>
        <div className="text-xs text-slate-400">
          {formatBytes(item.file.size)}
          {!isTradeReport && <span className="ml-1.5">· похоже на: {GUESS_LABEL[item.guess]}</span>}
        </div>
      </div>

      {/* Маршрут — единственное, что реально влияет на обработку файла: Trade Report
          уходит в специализированный загрузчик, всё остальное — в общий импортёр,
          который сам классифицирует документ на сервере (см. комментарий выше). */}
      <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5 text-xs">
        <button
          type="button"
          onClick={() => onChangeRoute('trade_report')}
          disabled={locked}
          className={cn('rounded-md px-2.5 py-1 font-medium transition', isTradeReport ? 'bg-brand-gradient text-white' : 'text-slate-600 hover:bg-slate-50')}
        >
          Trade Report
        </button>
        <button
          type="button"
          onClick={() => onChangeRoute('primary')}
          disabled={locked}
          className={cn('rounded-md px-2.5 py-1 font-medium transition', !isTradeReport ? 'bg-brand-gradient text-white' : 'text-slate-600 hover:bg-slate-50')}
        >
          Другой документ
        </button>
      </div>

      {isTradeReport && (
        <>
          <select
            className="input h-9 w-36 py-1 text-xs"
            value={item.cduId}
            onChange={(e) => onChangeCdu(e.target.value ? Number(e.target.value) : '')}
            disabled={locked}
          >
            <option value="">Автоопределение ЧДУ</option>
            {cdus.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <input
            type="date"
            className="input h-9 w-32 py-1 text-xs"
            value={item.tradeDate}
            onChange={(e) => onChangeDate(e.target.value)}
            disabled={locked}
          />
        </>
      )}

      <span className={STATUS_BADGE[item.status]}>
        {busy && <Loader2 className="mr-1 inline h-3 w-3 animate-spin" />}
        {STATUS_LABEL[item.status]}
      </span>
      {item.message && <span className="max-w-[220px] truncate text-xs text-slate-500" title={item.message}>{item.message}</span>}

      <div className="ml-auto flex items-center gap-1.5">
        {(item.status === 'queued' || item.status === 'error') && (
          <button type="button" onClick={onImport} className="btn-secondary h-8 px-2.5 text-xs">
            <UploadCloud className="h-3.5 w-3.5" />
            Импортировать
          </button>
        )}
        {item.status !== 'uploading' && (
          <button type="button" onClick={onRemove} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600" aria-label="Убрать из очереди">
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  )
}
