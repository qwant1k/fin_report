import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useDropzone } from 'react-dropzone'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  AlertTriangle,
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
import { apiErrorMessage } from '@/lib/notifications'
import { documentTypeLabel, processStatusLabel } from '@/lib/displayLabels'
import {
  GUESS_LABEL, makeQueueItems, useUploadProgress, useUploadQueue,
  type QueueItem, type QueueStatus, type UploadRoute,
} from '@/lib/uploadQueue'

const AUTO_KEY = 'kdif.upload.autostart'
function readAutoStart(): boolean {
  try { return localStorage.getItem(AUTO_KEY) !== '0' } catch { return true }
}

// Очередь загрузки — глобальная (lib/uploadQueue.ts): файлы импортируются в фоне,
// по несколько одновременно, и каждый документ доступен сразу после своей загрузки.
// Можно уйти со страницы и продолжать работу — прогресс виден в шапке.
// Реальные коды типа документа, которые хранит backend (см. Workday.tsx DOC_LABEL
// и api/routes/primary_data_routes.py::_to_doc_type) — используются в истории загрузок.
const BACKEND_DOC_ICON: Record<string, ReactNode> = {
  TRADE_REPORT: <FileSpreadsheet className="h-4 w-4 text-emerald-600" />,
  HOLDINGS: <FileSpreadsheet className="h-4 w-4 text-sky-600" />,
  RECONCILIATION: <FileText className="h-4 w-4 text-amber-600" />,
  CERTIFICATE: <FileText className="h-4 w-4 text-violet-600" />,
  STATEMENT_PDF: <FileText className="h-4 w-4 text-red-600" />,
  RISK_REPORT_XLSM: <FileText className="h-4 w-4 text-emerald-600" />,
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

  const queue = useUploadQueue((s) => s.items)
  const duplicate = useUploadQueue((s) => s.duplicate)
  const { add, update: updateItem, remove: removeItem, clearDone, start, resolveDuplicate: resolveDup } = useUploadQueue.getState()
  const progress = useUploadProgress()
  const [historyTab, setHistoryTab] = useState<'trade_report' | 'primary'>('trade_report')
  const [duplicateBusy, setDuplicateBusy] = useState<'replace' | 'new_version' | null>(null)
  const [autoStart, setAutoStart] = useState(readAutoStart)
  const toggleAutoStart = (v: boolean) => {
    setAutoStart(v)
    try { localStorage.setItem(AUTO_KEY, v ? '1' : '0') } catch { /* private mode */ }
  }

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

  const onDrop = useCallback(
    (accepted: File[]) => {
      if (!accepted.length) return
      add(makeQueueItems(accepted, workDate), autoStart)
      if (autoStart) toast(`Начата загрузка файлов: ${accepted.length}. Прогресс доступен в верхней панели.`, { icon: '⏳' })
    },
    [workDate, autoStart, add],
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: true,
    disabled: !canUploadAny,
  })

  const importAll = () => start()

  const resolveDuplicate = async (action: 'replace' | 'new_version') => {
    setDuplicateBusy(action)
    try {
      await resolveDup(action)
    } finally {
      setDuplicateBusy(null)
    }
  }

  const setCdu = useMutation({
    mutationFn: async ({ id, cduId }: { id: number; cduId: number }) =>
      (await api.put(`/upload/files/${id}/cdu`, null, { params: { cdu_id: cduId } })).data,
    onSuccess: () => {
      toast.success('Файл привязан к выбранному ЧДУ; данные обновлены.')
      qc.invalidateQueries({ queryKey: ['trade-files'] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось изменить ЧДУ для файла')),
  })

  const removeTradeFile = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/upload/files/${id}`)).data,
    onSuccess: () => {
      toast.success('Файл и связанные с ним импортированные данные удалены.')
      qc.invalidateQueries({ queryKey: ['trade-files'] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось удалить файл')),
  })

  const queuedCount = useMemo(() => queue.filter((it) => it.status === 'queued' || it.status === 'error').length, [queue])

  return (
    <div className="space-y-6">
      <PageHeader
        icon={UploadCloud}
        title="Загрузка документов"
        subtitle="Отчёты о сделках и первичные документы ЧДУ — в одном месте, с проверкой перед импортом"
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
              Отчёты о сделках, данные портфеля, файлы сверки, биржевые свидетельства, выписки PDF и файлы НБ РК — можно вперемешку
            </div>
            <div className="mt-3 flex items-center justify-center gap-2">
              <span className="badge-neutral">.xlsx</span>
              <span className="badge-neutral">.xlsm</span>
              <span className="badge-neutral">.pdf</span>
              <span className="badge-neutral">.docx</span>
              <span className="badge-neutral">.png</span>
              <span className="badge-neutral">.csv</span>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-slate-300 text-emerald-600"
                checked={autoStart}
                onChange={(e) => toggleAutoStart(e.target.checked)}
              />
              Загружать сразу после выбора файлов
            </label>
            <p className="flex items-start gap-1.5 text-xs text-slate-600">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
              <span>
                Файлы грузятся в фоне по 3 одновременно. Каждый документ доступен сразу после своей загрузки —
                не нужно ждать остальные. Можно перейти в{' '}
                <Link to="/workday" className="font-medium text-emerald-700 underline">Рабочий день</Link>{' '}
                или другой раздел: прогресс виден внизу экрана.
              </span>
            </p>
          </div>
        </div>
      )}

      {queue.length > 0 && (
        <div className="card overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-4">
            <div>
              <h2 className="section-title">Очередь на импорт</h2>
              <p className="text-sm text-slate-500">
                {progress.active + progress.waiting > 0
                  ? `Загружается: готово ${progress.done} из ${progress.total}${progress.failed ? `, ошибок ${progress.failed}` : ''} — можно продолжать работу`
                  : 'Для отчёта о сделках можно указать ЧДУ и дату; остальные документы сервер распознает сам'}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={clearDone}
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
                onImport={() => start([item.id])}
                onResolveDuplicate={() => useUploadQueue.getState().openDuplicate(item.id)}
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
                { value: 'trade_report', label: 'Отчёты о сделках' },
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
                        <span className="badge-ok"><CheckCircle2 className="mr-1 inline h-3 w-3" />{processStatusLabel(f.status)}</span>
                      ) : (
                        <span className="badge-warn"><AlertCircle className="mr-1 inline h-3 w-3" />{processStatusLabel(f.status)}</span>
                      )}
                    </td>
                    <td>
                      {canTradeReport && (
                        <button
                          onClick={async () => {
                            const { confirmed } = await confirm({
                              title: 'Удалить файл отчёта о сделках?',
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
                        {documentTypeLabel(d.file_type)}
                      </span>
                    </td>
                    <td>
                      <span className={cn('badge', d.import_status === 'OK' ? 'badge-ok' : d.import_status === 'ERROR' ? 'badge-breach' : 'badge-warn')}>
                        {processStatusLabel(d.import_status)}
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
        onClose={() => { if (!duplicateBusy) resolveDup('cancel') }}
        size="lg"
        title={
          <span className="flex items-center gap-2">
            <AlertCircle className="h-5 w-5 text-amber-500" /> Файл уже загружен
          </span>
        }
        description="Контрольная сумма совпадает с существующим файлом. Выберите действие."
        footer={
          <button disabled={!!duplicateBusy} onClick={() => resolveDup('cancel')} className="btn-secondary">
            Не загружать
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
              <div><span className="text-slate-500">Статус:</span> {processStatusLabel(duplicate.existing.status)}</div>
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
  onResolveDuplicate,
  onRemove,
}: {
  item: QueueItem
  cdus: CDU[]
  onChangeRoute: (r: UploadRoute) => void
  onChangeCdu: (id: number | '') => void
  onChangeDate: (d: string) => void
  onImport: () => void
  onResolveDuplicate: () => void
  onRemove: () => void
}) {
  const busy = item.status === 'uploading'
  const isTradeReport = item.route === 'trade_report'
  const locked = busy || item.status === 'done'

  return (
    <div>
    <div className="flex flex-wrap items-center gap-3 p-3">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100">
        {isTradeReport ? <FileSpreadsheet className="h-4 w-4 text-emerald-600" /> : <FileText className="h-4 w-4 text-slate-500" />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-slate-800" title={item.file.name}>{item.file.name}</div>
        <div className="text-xs text-slate-400">
          {formatBytes(item.file.size)}
          {!isTradeReport && <span className="ml-1.5">· похоже на: {GUESS_LABEL[item.guess]}</span>}
          {item.startedAt && item.status === 'uploading' && <Elapsed since={item.startedAt} />}
          {item.startedAt && item.finishedAt && (
            <span className="ml-1.5">· {Math.max(1, Math.round((item.finishedAt - item.startedAt) / 1000))} с</span>
          )}
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
          Отчёт о сделках
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
        {item.status === 'duplicate' && (
          <button type="button" onClick={onResolveDuplicate} className="btn-secondary h-8 px-2.5 text-xs text-amber-700">
            <AlertCircle className="h-3.5 w-3.5" />
            Выбрать действие
          </button>
        )}
        {item.status !== 'uploading' && (
          <button type="button" onClick={onRemove} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600" aria-label="Убрать из очереди">
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
    {!!item.anomalies?.length && (
      <div className="grid gap-2 border-t border-amber-100 bg-amber-50/40 px-3 py-3 md:grid-cols-2">
        {item.anomalies.map((anomaly, index) => (
          <div key={`${anomaly.kind}-${anomaly.trade_id}-${index}`} className={cn(
            'rounded-lg border px-3 py-2 text-xs',
            anomaly.severity === 'critical' ? 'border-rose-200 bg-rose-50 text-rose-800' : 'border-amber-200 bg-amber-50 text-amber-800',
          )}>
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <div className="font-semibold">{anomaly.title}</div>
                <div className="mt-0.5 opacity-90">{anomaly.message}</div>
                <div className="mt-1 text-[11px] opacity-70">Источник сравнения: {anomaly.source} · допуск {(anomaly.tolerance_pct * 100).toLocaleString('ru-RU', { maximumFractionDigits: 2 })}%</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    )}
    </div>
  )
}

function Elapsed({ since }: { since: number }) {
  const [, tick] = useState(0)
  // re-render every second while the file is being processed (OCR can take a minute)
  useEffect(() => {
    const t = window.setInterval(() => tick((n) => n + 1), 1000)
    return () => window.clearInterval(t)
  }, [])
  return <span className="ml-1.5">· {Math.round((Date.now() - since) / 1000)} с…</span>
}
