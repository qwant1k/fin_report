import { create } from 'zustand'
import { AxiosError } from 'axios'
import type { QueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { apiErrorMessage, notificationText } from '@/lib/notifications'

/**
 * Global background upload queue.
 *
 * Files are imported in the background, a few at a time (OCR of a certificate
 * takes 30–60 s, a Trade Report a second), so the user does not wait for the
 * whole batch: every document is available as soon as it is imported, and the
 * user can leave the «Загрузка документов» page — the queue lives in this
 * store, its progress is shown in the header (UploadIndicator).
 */
export type UploadRoute = 'trade_report' | 'primary'
export type QueueStatus = 'queued' | 'uploading' | 'done' | 'error' | 'duplicate'

// Preview-only guess (the server makes the final classification).
export type GuessedType =
  | 'trade_report' | 'holdings' | 'reconciliation' | 'exchange_certificate'
  | 'pdf_statement' | 'nbrk' | 'risk_report' | 'unknown'

export const GUESS_LABEL: Record<GuessedType, string> = {
  trade_report: 'Trade Report',
  holdings: 'Holdings',
  reconciliation: 'Сверка',
  exchange_certificate: 'Биржевое свидетельство',
  pdf_statement: 'Выписка PDF',
  nbrk: 'Выписка НБ РК (КФГД)',
  risk_report: 'Risk Report',
  unknown: 'тип определит сервер',
}

export function guessType(filename: string): GuessedType {
  const f = filename.toLowerCase()
  if (/(кфгд|kfgd)_\d{8}/.test(f)) return 'nbrk'
  if (f.endsWith('.xlsm') || f.includes('risk report') || f.includes('risk_report')) return 'risk_report'
  if (/\.(xlsx|xlsm)$/.test(f) && (f.includes('trade report') || f.includes('trade_report') || f.includes('сделки') || f.includes('trade'))) {
    return 'trade_report'
  }
  if (f.endsWith('.xlsx') && (f.includes('holdings') || f.includes('позиции') || f.includes('активах'))) return 'holdings'
  if (f.endsWith('.xlsx') && (f.includes('сверка') || f.includes('recon'))) return 'reconciliation'
  if (/\.(pdf|png|jpe?g|docx)$/.test(f) && (f.includes('биржев') || f.includes('certificate') || f.includes('cert'))) return 'exchange_certificate'
  if (f.endsWith('.pdf') && (f.includes('выписка') || f.includes('statement'))) return 'pdf_statement'
  if (f.endsWith('.xlsx')) return 'trade_report'
  return 'unknown'
}

export function makeQueueItems(files: File[], tradeDate: string): QueueItem[] {
  return files.map((file) => {
    const guess = guessType(file.name)
    return {
      id: `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      file,
      guess,
      route: guess === 'trade_report' ? 'trade_report' : 'primary',
      cduId: '',
      tradeDate,
      status: 'queued',
    }
  })
}

export interface QueueItem {
  id: string
  file: File
  guess: GuessedType
  route: UploadRoute
  cduId: number | ''
  tradeDate: string
  status: QueueStatus
  message?: string
  startedAt?: number
  finishedAt?: number
  /** the already uploaded file, when the server reported a duplicate */
  existing?: DuplicateExisting
}

export interface DuplicateExisting {
  file_id: number
  filename: string
  uploaded_at: string | null
  uploaded_by: string | null
  trade_date: string | null
  status: string
  rows_parsed: number
}

const CONCURRENCY = 3
let queryClient: QueryClient | null = null
export function bindUploadQueryClient(qc: QueryClient) {
  queryClient = qc
}

function invalidateAfterImport() {
  if (!queryClient) return
  for (const key of ['trade-files', 'primary-documents', 'workday', 'dashboard', 'positions', 'reconciliation']) {
    queryClient.invalidateQueries({ queryKey: [key] })
  }
}

interface UploadQueueState {
  items: QueueItem[]
  duplicate: { item: QueueItem; existing: DuplicateExisting } | null
  add: (items: QueueItem[], autoStart?: boolean) => void
  update: (id: string, patch: Partial<QueueItem>) => void
  remove: (id: string) => void
  clearDone: () => void
  start: (ids?: string[]) => void
  openDuplicate: (id: string) => void
  resolveDuplicate: (action: 'replace' | 'new_version' | 'cancel') => Promise<void>
}

async function uploadTradeReport(item: QueueItem, onDuplicate?: 'replace' | 'new_version') {
  const fd = new FormData()
  fd.append('file', item.file)
  if (item.cduId) fd.append('cdu_id', String(item.cduId))
  if (item.tradeDate) fd.append('trade_date', item.tradeDate)
  if (onDuplicate) fd.append('on_duplicate', onDuplicate)
  return (await api.post('/upload/trade-report', fd, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 600_000 })).data
}

async function uploadPrimary(item: QueueItem) {
  const fd = new FormData()
  fd.append('file', item.file)
  return (await api.post('/primary-data/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 600_000 })).data
}

export const useUploadQueue = create<UploadQueueState>((set, get) => {
  const patch = (id: string, p: Partial<QueueItem>) =>
    set((s) => ({ items: s.items.map((it) => (it.id === id ? { ...it, ...p } : it)) }))

  const process = async (item: QueueItem, onDuplicate?: 'replace' | 'new_version') => {
    patch(item.id, { status: 'uploading', message: undefined, startedAt: Date.now() })
    try {
      if (item.route === 'trade_report') {
        const r = await uploadTradeReport(item, onDuplicate)
        const pc = r?.price_check
        if (pc?.flagged > 0) {
          toast(`Сверка с KASE: в ${pc.flagged} из ${pc.checked} сделок использована цена KASE из-за расхождения.`, { icon: '⚑', duration: 6000 })
        }
        patch(item.id, {
          status: 'done', finishedAt: Date.now(),
          message: `${r.cdu_name ?? ''} · ${r.rows_parsed} строк`.replace(/^ · /, ''),
        })
      } else {
        const r = await uploadPrimary(item)
        // backend answers HTTP 200 with status FAILED/SKIPPED in the body
        if (r.status === 'FAILED') {
          patch(item.id, { status: 'error', finishedAt: Date.now(), message: notificationText(r.message, 'Импорт документа не выполнен') })
        } else if (r.status === 'SKIPPED') {
          patch(item.id, { status: 'done', finishedAt: Date.now(), message: 'Пропущено — файл уже загружен ранее' })
        } else {
          patch(item.id, { status: 'done', finishedAt: Date.now(), message: notificationText(r.message, 'Документ импортирован') })
        }
      }
      invalidateAfterImport()
    } catch (err) {
      const axErr = err as AxiosError<{ detail?: any }>
      const detail = axErr.response?.data?.detail
      if (item.route === 'trade_report' && axErr.response?.status === 409 && detail?.error === 'duplicate_file') {
        const existing = detail.existing as DuplicateExisting
        patch(item.id, { status: 'duplicate', message: 'Такой файл уже загружен — выберите действие', existing })
        if (!get().duplicate) set({ duplicate: { item, existing } })
        return
      }
      const message = apiErrorMessage(err, `Не удалось импортировать файл «${item.file.name}»`)
      patch(item.id, { status: 'error', finishedAt: Date.now(), message })
    }
  }

  // simple pool: keeps CONCURRENCY uploads running while there are queued items marked to run
  const pending = new Set<string>()
  let running = 0
  let batchStartedAt = 0
  const pump = () => {
    if (running === 0 && batchStartedAt === 0) batchStartedAt = Date.now()
    while (running < CONCURRENCY) {
      const next = get().items.find((it) => pending.has(it.id) && it.status === 'queued')
      if (!next) break
      pending.delete(next.id)
      running += 1
      process(next).finally(() => {
        running -= 1
        const all = get().items
        if (running === 0 && !all.some((it) => it.status === 'queued' && pending.has(it.id))) {
          const batch = all.filter((it) => (it.finishedAt ?? 0) >= batchStartedAt)
          const done = batch.filter((it) => it.status === 'done').length
          const failed = batch.filter((it) => it.status === 'error').length
          batchStartedAt = 0
          if (failed > 0) {
            toast.error(`Загрузка завершена: успешно ${done}, с ошибками ${failed}. Откройте очередь для подробностей.`)
          } else if (done > 1) {
            toast.success(`Загрузка завершена: успешно обработано файлов ${done}.`)
          } else if (done === 1) {
            toast.success(`Файл «${batch.find((it) => it.status === 'done')?.file.name ?? ''}» успешно загружен и обработан.`)
          }
        }
        pump()
      })
    }
  }

  return {
    items: [],
    duplicate: null,
    add: (items, autoStart) => {
      set((s) => ({ items: [...s.items, ...items] }))
      if (autoStart) get().start(items.map((it) => it.id))
    },
    update: (id, p) => patch(id, p),
    remove: (id) => set((s) => ({ items: s.items.filter((it) => it.id !== id || it.status === 'uploading') })),
    clearDone: () => set((s) => ({ items: s.items.filter((it) => it.status !== 'done') })),
    start: (ids) => {
      const items = get().items
      for (const it of items) {
        if ((ids ? ids.includes(it.id) : true) && (it.status === 'queued' || it.status === 'error')) {
          if (it.status === 'error') patch(it.id, { status: 'queued', message: undefined })
          pending.add(it.id)
        }
      }
      pump()
    },
    openDuplicate: (id) => {
      const it = get().items.find((x) => x.id === id)
      if (it?.existing) set({ duplicate: { item: it, existing: it.existing } })
    },
    resolveDuplicate: async (action) => {
      const dup = get().duplicate
      if (!dup) return
      set({ duplicate: null })
      if (action === 'cancel') {
        patch(dup.item.id, { status: 'error', message: 'Отменено: файл уже был загружен' })
      } else {
        await process(dup.item, action)
      }
      // next duplicate waiting for a decision
      const next = get().items.find((it) => it.status === 'duplicate' && it.id !== dup.item.id)
      if (next) {
        set({ duplicate: { item: next, existing: next.existing ?? { file_id: 0, filename: next.file.name, uploaded_at: null, uploaded_by: null, trade_date: null, status: '', rows_parsed: 0 } } })
      }
    },
  }
})

export function useUploadProgress() {
  const items = useUploadQueue((s) => s.items)
  const total = items.length
  const done = items.filter((it) => it.status === 'done').length
  const failed = items.filter((it) => it.status === 'error').length
  const active = items.filter((it) => it.status === 'uploading').length
  const waiting = items.filter((it) => it.status === 'queued').length
  const duplicates = items.filter((it) => it.status === 'duplicate').length
  return { total, done, failed, active, waiting, duplicates }
}
