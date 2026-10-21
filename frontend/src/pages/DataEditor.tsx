import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Columns3, Copy, Database, Download, Edit3, Filter,
  Info, Loader2, Lock, Plus, RefreshCw, Save, Search, Trash2, X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'

import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { useConfirm } from '@/lib/confirm'
import { Modal } from '@/components/ui'
import { apiErrorMessage } from '@/lib/notifications'
import {
  alertSeverityLabel,
  categoryLabel,
  operationLabel,
  portfolioTypeLabel,
  processStatusLabel,
  sourceLabel,
  workflowStatusLabel,
} from '@/lib/displayLabels'

// ─────────────── types ───────────────

interface EditHint { label: string; route: string }

interface TableInfo {
  name: string
  label: string
  group: string
  description: string
  rows: number | null
  read_only?: boolean
  edit_hint?: EditHint | null
}

type ColType = 'string' | 'integer' | 'float' | 'boolean' | 'date' | 'datetime' | 'text'

interface ColumnMeta {
  name: string
  label: string
  type: ColType
  nullable: boolean
  required: boolean
  default: string | null
  max_length: number | null
  fk_table: string | null
  technical: boolean
}

interface TableMeta {
  name: string
  label: string
  description: string
  columns: ColumnMeta[]
  read_only?: boolean
  edit_hint?: EditHint | null
}

type Row = Record<string, unknown>

interface ListResponse {
  data: Row[]
  total: number
  page: number
  page_size: number
  fk_labels?: Record<string, Record<string, string>>
}

// ─────────────── formatting ───────────────

function fmtDate(v: string): string {
  const [y, m, d] = v.slice(0, 10).split('-')
  return d && m && y ? `${d}.${m}.${y}` : v
}

const CATEGORY_VALUES: Record<string, string> = {
  CASH: 'Деньги', GOV_BONDS: 'ГЦБ (МФ РК)', REVERSE_REPO: 'Обратное РЕПО', MFO_BONDS: 'МФО',
  AGENCY_BONDS: 'Агентские', FOREIGN_BONDS: 'Иностранные ЦБ', DEPOSIT: 'Депозиты',
  RECEIVABLES: 'Дебиторка', OTHER: 'Прочее',
}
const VALUE_LABELS: Record<string, Record<string, string>> = {
  category: CATEGORY_VALUES,
  instrument_category: CATEGORY_VALUES,
  target_category: CATEGORY_VALUES,
  workflow_status: {
    APPROVED: 'Согласовано', PENDING_APPROVAL: 'На согласовании', PENDING_CANCELLATION: 'Аннулирование на согласовании',
    REJECTED: 'Отклонено', CANCELLED: 'Аннулировано',
  },
  portfolio_type: { PRIVATE_CDU: 'ЧДУ', NBRK_OWN: 'НБ РК — собственные', NBRK_RESERVE: 'НБ РК — спецрезерв' },
  operation_type: {
    BUY: 'Покупка', SELL: 'Продажа', REPO_OPEN: 'Открытие РЕПО', REPO_CLOSE: 'Закрытие РЕПО', COUPON: 'Купон',
    REDEMPTION: 'Погашение', DEPOSIT_OPEN: 'Размещение депозита', DEPOSIT_CLOSE: 'Возврат депозита',
  },
  severity: { INFO: 'Информация', WARN: 'Предупреждение', CRITICAL: 'Критично' },
}

function displayValue(value: unknown, col: ColumnMeta, fk?: Record<string, string>): string {
  if (value === null || value === undefined || value === '') return '—'
  if (col.fk_table && fk) return fk[String(value)] ?? `#${value}`
  const named = VALUE_LABELS[col.name]?.[String(value)]
  if (named) return named
  if (['category', 'instrument_category', 'target_category'].includes(col.name)) return categoryLabel(value)
  if (col.name === 'operation_type' || col.name === 'movement_type') return operationLabel(value)
  if (col.name === 'workflow_status') return workflowStatusLabel(value)
  if (['status', 'import_status', 'parse_status'].includes(col.name)) return processStatusLabel(value)
  if (col.name === 'portfolio_type') return portfolioTypeLabel(value)
  if (col.name === 'severity') return alertSeverityLabel(value)
  if (col.name === 'source' || col.name.endsWith('_source')) return sourceLabel(value)
  if (col.type === 'boolean') return value ? 'Да' : 'Нет'
  if (col.type === 'date' && typeof value === 'string') return fmtDate(value)
  if (col.type === 'datetime' && typeof value === 'string') return `${fmtDate(value)} ${value.slice(11, 16)}`
  if (typeof value === 'number') {
    return value.toLocaleString('ru-RU', { maximumFractionDigits: col.type === 'integer' ? 0 : 6 })
  }
  return String(value)
}

function toInput(value: unknown, type: ColType): string {
  if (value === null || value === undefined) return ''
  if (type === 'datetime' && typeof value === 'string') return value.slice(0, 16)
  if (type === 'date' && typeof value === 'string') return value.slice(0, 10)
  return String(value)
}

function fromInput(raw: string | boolean, type: ColType): unknown {
  if (type === 'boolean') return typeof raw === 'string' ? raw === 'true' : Boolean(raw)
  const s = String(raw)
  if (s.trim() === '') return null
  return s // the server converts and validates (comma decimals, dd.mm.yyyy, …)
}

// ─────────────── page ───────────────

export default function DataEditorPage() {
  const qc = useQueryClient()
  const confirm = useConfirm()
  const canEditTables = useAuthStore((s) => s.can('data_editor.edit'))

  const [table, setTable] = useState('')
  const [tableSearch, setTableSearch] = useState('')
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [sort, setSort] = useState<{ col: string; order: 'asc' | 'desc' }>({ col: 'id', order: 'desc' })
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [showFilters, setShowFilters] = useState(false)
  const [showTechnical, setShowTechnical] = useState(false)
  const [modal, setModal] = useState<{ mode: 'create' | 'edit'; row: Row } | null>(null)
  const [cell, setCell] = useState<{ id: number; col: string; value: string } | null>(null)

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(search), 300)
    return () => window.clearTimeout(t)
  }, [search])

  const tablesQ = useQuery<TableInfo[]>({
    queryKey: ['data-editor', 'tables'],
    queryFn: async () => (await api.get('/data/tables')).data,
  })
  const metaQ = useQuery<TableMeta>({
    queryKey: ['data-editor', 'meta', table],
    queryFn: async () => (await api.get(`/data/tables/${table}/meta`)).data,
    enabled: !!table,
  })
  const canWrite = canEditTables && !metaQ.data?.read_only

  const params = useMemo(() => {
    const p: Record<string, string | number> = { page, page_size: pageSize, sort: sort.col, order: sort.order }
    if (debounced) p.search = debounced
    for (const [k, v] of Object.entries(filters)) if (v !== '') p[k] = v
    return p
  }, [page, pageSize, sort, debounced, filters])

  const rowsQ = useQuery<ListResponse>({
    queryKey: ['data-editor', 'rows', table, params],
    queryFn: async () => (await api.get(`/data/tables/${table}`, { params })).data,
    enabled: !!table,
    placeholderData: (prev) => prev,
  })

  useEffect(() => { setPage(1) }, [table, debounced, filters, pageSize])
  useEffect(() => {
    if (!table && tablesQ.data?.length) {
      setTable((tablesQ.data.find((t) => t.name === 'cdu_limits') ?? tablesQ.data[0]).name)
    }
  }, [tablesQ.data, table])

  const selectTable = (name: string) => {
    setTable(name); setFilters({}); setSearch(''); setSort({ col: 'id', order: 'desc' }); setCell(null)
  }

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['data-editor', 'rows', table] })
    qc.invalidateQueries({ queryKey: ['data-editor', 'tables'] })
  }

  const saveM = useMutation({
    mutationFn: async ({ id, payload }: { id?: number; payload: Row }) =>
      id ? (await api.patch(`/data/tables/${table}/${id}`, payload)).data
        : (await api.post(`/data/tables/${table}`, payload)).data,
    onSuccess: (_, v) => {
      toast.success(v.id ? 'Изменения записи сохранены.' : 'Новая запись добавлена в справочник.')
      setModal(null); setCell(null); refresh()
    },
    onError: (error) => toast.error(apiErrorMessage(error, 'Не удалось сохранить запись справочника')),
  })
  const deleteM = useMutation({
    mutationFn: async (id: number) => api.delete(`/data/tables/${table}/${id}`),
    onSuccess: () => { toast.success('Запись удалена из справочника.'); refresh() },
    onError: (error) => toast.error(apiErrorMessage(error, 'Не удалось удалить запись справочника')),
  })

  const handleDelete = async (row: Row) => {
    const { confirmed } = await confirm({
      title: 'Удалить запись?',
      description: `Запись №${row.id} из «${metaQ.data?.label}» будет удалена безвозвратно. Изменение записывается в журнал аудита.`,
      tone: 'danger',
      confirmLabel: 'Удалить',
    })
    if (confirmed) deleteM.mutate(Number(row.id))
  }

  const columns = useMemo(
    () => (metaQ.data?.columns ?? []).filter((c) => showTechnical || !c.technical),
    [metaQ.data, showTechnical],
  )
  const hiddenCount = (metaQ.data?.columns.length ?? 0) - columns.length
  const total = rowsQ.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const fk = rowsQ.data?.fk_labels ?? {}
  const current = tablesQ.data?.find((t) => t.name === table)

  const groups = useMemo(() => {
    const q = tableSearch.trim().toLowerCase()
    const out: Record<string, TableInfo[]> = {}
    for (const t of tablesQ.data ?? []) {
      if (q && !t.label.toLowerCase().includes(q) && !t.description.toLowerCase().includes(q)) continue
      ;(out[t.group] ??= []).push(t)
    }
    return out
  }, [tablesQ.data, tableSearch])

  const exportCsv = () => {
    const rows = rowsQ.data?.data ?? []
    const header = ['№', ...columns.map((c) => c.label)]
    const lines = [header, ...rows.map((r) => [String(r.id), ...columns.map((c) => {
      const v = displayValue(r[c.name], c, fk[c.name])
      return v === '—' ? '' : v
    })])]
    const csv = lines.map((l) => l.map((x) => `"${String(x).replace(/"/g, '""')}"`).join(';')).join('\r\n')
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${metaQ.data?.label ?? table}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const commitCell = () => {
    if (!cell) return
    const col = metaQ.data?.columns.find((c) => c.name === cell.col)
    const row = rowsQ.data?.data.find((r) => r.id === cell.id)
    if (!col || !row) return setCell(null)
    if (toInput(row[col.name], col.type) === cell.value) return setCell(null)
    saveM.mutate({ id: cell.id, payload: { [col.name]: fromInput(cell.value, col.type) } })
  }

  return (
    <div className="flex min-h-[calc(100vh-6rem)] flex-col gap-3 lg:flex-row">
      {/* ─── tables ─── */}
      <aside className="flex w-full shrink-0 flex-col rounded-xl border border-slate-300 bg-white lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:w-72">
        <div className="border-b border-slate-200 p-3">
          <div className="mb-2 flex items-center gap-2 text-sm font-bold text-slate-800">
            <Database className="h-4 w-4 text-emerald-600" /> Редактор базы данных
          </div>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
            <input value={tableSearch} onChange={(e) => setTableSearch(e.target.value)} placeholder="Найти таблицу…"
              className="input h-8 py-1 pl-8 text-sm" />
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto p-2">
          {tablesQ.isLoading && <div className="flex items-center gap-2 p-2 text-xs text-slate-500"><Loader2 className="h-3 w-3 animate-spin" />Загрузка…</div>}
          {Object.entries(groups).map(([group, items]) => (
            <div key={group} className="mb-2">
              <div className="px-2 pb-1 pt-2 text-[11px] font-bold uppercase tracking-wide text-slate-500">{group}</div>
              {items.map((t) => (
                <button key={t.name} onClick={() => selectTable(t.name)} title={t.description}
                  className={clsx(
                    'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition',
                    table === t.name ? 'bg-emerald-600 font-semibold text-white' : 'text-slate-700 hover:bg-slate-100',
                  )}>
                  {t.read_only
                    ? <Lock className={clsx('h-3 w-3 shrink-0', table === t.name ? 'text-white/80' : 'text-slate-400')} />
                    : <Edit3 className={clsx('h-3 w-3 shrink-0', table === t.name ? 'text-white/80' : 'text-emerald-600')} />}
                  <span className="min-w-0 flex-1 truncate">{t.label}</span>
                  {t.rows != null && (
                    <span className={clsx('text-[11px] tabular-nums', table === t.name ? 'text-white/80' : 'text-slate-400')}>
                      {t.rows.toLocaleString('ru-RU')}
                    </span>
                  )}
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="border-t border-slate-200 p-2 text-[11px] text-slate-500">
          <Edit3 className="mr-1 inline h-3 w-3 text-emerald-600" />можно править ·
          <Lock className="mx-1 inline h-3 w-3" />только просмотр
        </div>
      </aside>

      {/* ─── grid ─── */}
      <main className="flex min-w-0 flex-1 flex-col rounded-xl border border-slate-300 bg-white">
        <div className="border-b border-slate-200 px-4 py-3">
          <div className="mb-2">
            <h1 className="text-lg font-bold text-slate-900">{metaQ.data?.label ?? current?.label ?? '…'}</h1>
            {metaQ.data?.description && <p className="text-sm text-slate-600">{metaQ.data.description}</p>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex flex-1 flex-wrap items-center gap-2">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Поиск по тексту…"
                  className="input h-9 w-56 py-1 pl-8" />
              </div>
              <button onClick={() => setShowFilters((v) => !v)} className={clsx('btn-secondary h-9 px-3 text-xs', showFilters && 'border-emerald-400 bg-emerald-50')}>
                <Filter className="h-3.5 w-3.5" /> Фильтры{Object.values(filters).filter(Boolean).length ? ` (${Object.values(filters).filter(Boolean).length})` : ''}
              </button>
              {(showTechnical || hiddenCount > 0) && (
                <button onClick={() => setShowTechnical((v) => !v)} className="btn-secondary h-9 px-3 text-xs"
                  title="Служебные колонки: даты создания, контрольные суммы, JSON">
                  <Columns3 className="h-3.5 w-3.5" /> {showTechnical ? 'Скрыть служебные' : `Служебные колонки (${hiddenCount})`}
                </button>
              )}
              <button onClick={exportCsv} className="btn-secondary h-9 px-3 text-xs" title="Выгрузить текущую страницу в CSV (Excel)">
                <Download className="h-3.5 w-3.5" /> CSV
              </button>
              <button onClick={() => rowsQ.refetch()} className="btn-secondary h-9 px-2.5" title="Обновить">
                <RefreshCw className={clsx('h-3.5 w-3.5', rowsQ.isFetching && 'animate-spin')} />
              </button>
              {canWrite && (
                <button onClick={() => setModal({ mode: 'create', row: {} })} className="btn-primary h-9 px-3 text-sm">
                  <Plus className="h-4 w-4" /> Добавить
                </button>
              )}
            </div>
          </div>
          {metaQ.data?.read_only ? (
            <div className="mt-2 flex flex-wrap items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-700">
              <Lock className="h-3.5 w-3.5 text-slate-500" />
              Таблица только для просмотра: данные формируются загрузкой документов, расчётом или требуют согласования.
              {metaQ.data.edit_hint && (
                <Link to={metaQ.data.edit_hint.route} className="font-semibold text-emerald-700 underline">
                  Изменить через «{metaQ.data.edit_hint.label}»
                </Link>
              )}
            </div>
          ) : canWrite ? (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-slate-500">
              <Info className="h-3.5 w-3.5" /> Двойной щелчок по ячейке — правка на месте (Enter — сохранить, Esc — отмена). Все изменения пишутся в журнал аудита.
            </div>
          ) : null}
        </div>

        <div className="min-h-0 flex-1 overflow-auto">
          {metaQ.isLoading || (rowsQ.isLoading && !rowsQ.data) ? (
            <div className="flex h-64 items-center justify-center gap-2 text-slate-500"><Loader2 className="h-5 w-5 animate-spin" /> Загрузка…</div>
          ) : (
            <table className="detail-table">
              <thead className="sticky top-0 z-10">
                <tr>
                  <th className="w-14">№</th>
                  {columns.map((c) => (
                    <th key={c.name} title={`${c.name}${c.required ? ' · обязательное' : ''}`}
                      onClick={() => setSort((s) => ({ col: c.name, order: s.col === c.name && s.order === 'asc' ? 'desc' : 'asc' }))}
                      className="cursor-pointer select-none whitespace-nowrap hover:bg-slate-200">
                      <span className="inline-flex items-center gap-1">
                        {c.label}{c.required && <span className="text-red-500">*</span>}
                        {sort.col === c.name && (sort.order === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
                      </span>
                    </th>
                  ))}
                  {canWrite && <th className="w-24 text-center">Действия</th>}
                </tr>
                {showFilters && (
                  <tr>
                    <th className="bg-white" />
                    {columns.map((c) => (
                      <th key={c.name} className="bg-white p-1 normal-case">
                        <FilterInput col={c} value={filters[c.name] ?? ''} onChange={(v) => setFilters((f) => ({ ...f, [c.name]: v }))} />
                      </th>
                    ))}
                    {canWrite && (
                      <th className="bg-white p-1 text-center normal-case">
                        <button onClick={() => setFilters({})} className="text-[11px] font-medium text-red-600 hover:underline">Сбросить</button>
                      </th>
                    )}
                  </tr>
                )}
              </thead>
              <tbody>
                {(rowsQ.data?.data ?? []).map((row) => (
                  <tr key={String(row.id)}>
                    <td className="font-mono text-[11px] text-slate-500">{String(row.id)}</td>
                    {columns.map((c) => {
                      const editing = cell && cell.id === row.id && cell.col === c.name
                      const v = row[c.name]
                      const empty = v === null || v === undefined || v === ''
                      return (
                        <td key={c.name}
                          onDoubleClick={() => canWrite && !c.technical && setCell({ id: Number(row.id), col: c.name, value: toInput(v, c.type) })}
                          className={clsx(
                            (c.type === 'integer' || c.type === 'float') && !c.fk_table && 'num',
                            canWrite && !c.technical && 'cursor-text',
                            editing && 'bg-emerald-50 p-0',
                          )}>
                          {editing ? (
                            <CellEditor col={c} value={cell!.value} onChange={(value) => setCell({ ...cell!, value })}
                              onCommit={commitCell} onCancel={() => setCell(null)} />
                          ) : c.type === 'boolean' ? (
                            <span className={clsx('rounded px-1.5 py-0.5 text-[11px] font-semibold', v ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600')}>
                              {v ? 'Да' : 'Нет'}
                            </span>
                          ) : (
                            <span className={clsx('block max-w-[22rem] truncate', empty && 'text-slate-300')}
                              title={empty ? undefined : String(v)}>
                              {displayValue(v, c, fk[c.name])}
                            </span>
                          )}
                        </td>
                      )
                    })}
                    {canWrite && (
                      <td className="whitespace-nowrap text-center">
                        <button onClick={() => setModal({ mode: 'edit', row })} className="rounded p-1 text-slate-500 hover:bg-emerald-100 hover:text-emerald-700" title="Открыть карточку">
                          <Edit3 className="h-3.5 w-3.5" />
                        </button>
                        <button onClick={() => setModal({ mode: 'create', row: { ...row, id: undefined } })} className="rounded p-1 text-slate-500 hover:bg-sky-100 hover:text-sky-700" title="Копировать в новую запись">
                          <Copy className="h-3.5 w-3.5" />
                        </button>
                        <button onClick={() => handleDelete(row)} className="rounded p-1 text-slate-500 hover:bg-red-100 hover:text-red-700" title="Удалить">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
                {rowsQ.data && rowsQ.data.data.length === 0 && (
                  <tr><td colSpan={columns.length + 2} className="py-12 text-center text-slate-500">
                    {debounced || Object.values(filters).some(Boolean) ? 'Ничего не найдено — измените поиск или фильтры' : 'Таблица пуста'}
                  </td></tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 px-4 py-2 text-xs text-slate-600">
          <span>
            {total ? `${((page - 1) * pageSize + 1).toLocaleString('ru-RU')}–${Math.min(page * pageSize, total).toLocaleString('ru-RU')} из ${total.toLocaleString('ru-RU')}` : '0 записей'}
          </span>
          <div className="flex items-center gap-2">
            <span>Строк на странице</span>
            <select value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))} className="input h-7 w-20 py-0 text-xs">
              {[20, 50, 100, 200, 500].map((n) => <option key={n}>{n}</option>)}
            </select>
            <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className="btn-secondary h-7 px-2"><ChevronLeft className="h-3.5 w-3.5" /></button>
            <span className="tabular-nums">{page} / {totalPages}</span>
            <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages} className="btn-secondary h-7 px-2"><ChevronRight className="h-3.5 w-3.5" /></button>
          </div>
        </div>
      </main>

      {modal && metaQ.data && (
        <RowModal
          mode={modal.mode}
          meta={metaQ.data}
          row={modal.row}
          saving={saveM.isPending}
          onClose={() => setModal(null)}
          onSubmit={(payload) => saveM.mutate({ id: modal.mode === 'edit' ? Number(modal.row.id) : undefined, payload })}
        />
      )}
    </div>
  )
}

// ─────────────── cells and filters ───────────────

function CellEditor({ col, value, onChange, onCommit, onCancel }: {
  col: ColumnMeta; value: string; onChange: (v: string) => void; onCommit: () => void; onCancel: () => void
}) {
  const ref = useRef<HTMLInputElement & HTMLSelectElement>(null)
  useEffect(() => { ref.current?.focus(); if (ref.current && 'select' in ref.current) ref.current.select?.() }, [])
  const keys = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') { e.preventDefault(); onCommit() }
    if (e.key === 'Escape') onCancel()
  }
  if (col.fk_table) {
    return <FkSelect table={col.fk_table} value={value} autoFocus onChange={(v) => onChange(v)} onBlur={onCommit} onKeyDown={keys} />
  }
  if (col.type === 'boolean') {
    return (
      <select ref={ref} value={value === 'true' ? 'true' : 'false'} onChange={(e) => onChange(e.target.value)} onBlur={onCommit} onKeyDown={keys}
        className="w-full border-0 bg-transparent px-2 py-1 text-[13px] focus:ring-2 focus:ring-emerald-500">
        <option value="true">Да</option><option value="false">Нет</option>
      </select>
    )
  }
  return (
    <input ref={ref} value={value} onChange={(e) => onChange(e.target.value)} onBlur={onCommit} onKeyDown={keys}
      type={col.type === 'date' ? 'date' : col.type === 'datetime' ? 'datetime-local' : 'text'}
      inputMode={col.type === 'integer' || col.type === 'float' ? 'decimal' : undefined}
      className="w-full min-w-[8rem] border-0 bg-white px-2 py-1 text-[13px] focus:ring-2 focus:ring-emerald-500" />
  )
}

function FilterInput({ col, value, onChange }: { col: ColumnMeta; value: string; onChange: (v: string) => void }) {
  const cls = 'w-full min-w-[6rem] rounded border border-slate-300 px-1.5 py-0.5 text-[12px] font-normal text-slate-800 focus:border-emerald-500 focus:outline-none'
  if (col.type === 'boolean') {
    return (
      <select value={value} onChange={(e) => onChange(e.target.value)} className={cls}>
        <option value="">все</option><option value="true">Да</option><option value="false">Нет</option>
      </select>
    )
  }
  if (col.fk_table) return <FkSelect table={col.fk_table} value={value} onChange={onChange} className={cls} emptyLabel="все" />
  if (col.type === 'date' || col.type === 'datetime') {
    return <input type="date" value={value} onChange={(e) => onChange(e.target.value)} className={cls} />
  }
  return <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={col.type === 'string' || col.type === 'text' ? 'содержит…' : '='} className={cls} />
}

function FkSelect({ table, value, onChange, className, emptyLabel = '— не выбрано —', autoFocus, onBlur, onKeyDown }: {
  table: string; value: string; onChange: (v: string) => void; className?: string; emptyLabel?: string
  autoFocus?: boolean; onBlur?: () => void; onKeyDown?: (e: React.KeyboardEvent) => void
}) {
  const q = useQuery<Array<{ id: number; label: string }>>({
    queryKey: ['data-editor', 'lookup', table],
    queryFn: async () => (await api.get(`/data/lookup/${table}`, { params: { limit: 1000 } })).data,
    staleTime: 60_000,
  })
  return (
    <select value={value} autoFocus={autoFocus} onBlur={onBlur} onKeyDown={onKeyDown} onChange={(e) => onChange(e.target.value)}
      className={className ?? 'w-full border-0 bg-white px-2 py-1 text-[13px] focus:ring-2 focus:ring-emerald-500'}>
      <option value="">{emptyLabel}</option>
      {(q.data ?? []).map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
      {value && q.data && !q.data.some((o) => String(o.id) === value) && <option value={value}>#{value}</option>}
    </select>
  )
}

// ─────────────── card (create / edit) ───────────────

function RowModal({ mode, meta, row, saving, onClose, onSubmit }: {
  mode: 'create' | 'edit'; meta: TableMeta; row: Row; saving: boolean
  onClose: () => void; onSubmit: (payload: Row) => void
}) {
  const editable = meta.columns.filter((c) => !['created_at', 'updated_at'].includes(c.name))
  const initial = useMemo(() => {
    const out: Record<string, string | boolean> = {}
    for (const c of editable) {
      const v = mode === 'create' && row[c.name] === undefined ? c.default : row[c.name]
      out[c.name] = c.type === 'boolean' ? (v === true || v === 'True' || v === 'true' || v === '1') : toInput(v, c.type)
    }
    return out
  }, [meta, row, mode]) // eslint-disable-line react-hooks/exhaustive-deps
  const [form, setForm] = useState(initial)
  const [showTech, setShowTech] = useState(false)
  useEffect(() => setForm(initial), [initial])

  const missing = editable.filter((c) => c.required && c.type !== 'boolean' && String(form[c.name] ?? '').trim() === '')

  const submit = () => {
    if (missing.length) {
      toast.error(`Заполните обязательные поля: ${missing.map((c) => c.label).join(', ')}.`)
      return
    }
    const payload: Row = {}
    for (const c of editable) {
      if (mode === 'edit' && form[c.name] === initial[c.name]) continue   // only changed fields (incl. cleared ones)
      if (mode === 'create' && (form[c.name] === '' || form[c.name] === undefined)) continue
      payload[c.name] = fromInput(form[c.name], c.type)
    }
    if (mode === 'edit' && Object.keys(payload).length === 0) { onClose(); return }
    onSubmit(payload)
  }

  const visible = editable.filter((c) => showTech || !c.technical)
  return (
    <Modal open onClose={() => !saving && onClose()} size="xl"
      title={mode === 'create' ? `Новая запись — ${meta.label}` : `${meta.label} — запись №${String(row.id)}`}
      description="Поля со звёздочкой обязательны. Числа можно вводить с запятой, даты — в формате дд.мм.гггг."
      footer={
        <>
          <button className="btn-ghost mr-auto text-xs" onClick={() => setShowTech((v) => !v)}>
            {showTech ? 'Скрыть служебные поля' : 'Показать служебные поля'}
          </button>
          <button className="btn-secondary" onClick={onClose} disabled={saving}>Отмена</button>
          <button className="btn-primary" onClick={submit} disabled={saving}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {mode === 'create' ? 'Добавить' : 'Сохранить'}
          </button>
        </>
      }>
      <div className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
        {visible.map((c) => (
          <label key={c.name} className={clsx('block', c.type === 'text' && 'sm:col-span-2 lg:col-span-3')}>
            <span className="mb-0.5 flex items-baseline justify-between gap-2 text-xs font-semibold text-slate-700">
              <span>{c.label}{c.required && <span className="ml-0.5 text-red-500">*</span>}</span>
              <span className="font-mono text-[10px] font-normal text-slate-400">{c.name}</span>
            </span>
            {c.type === 'boolean' ? (
              <span className="flex h-9 items-center gap-2">
                <input type="checkbox" checked={Boolean(form[c.name])} onChange={(e) => setForm((f) => ({ ...f, [c.name]: e.target.checked }))}
                  className="h-4 w-4 rounded border-slate-300 text-emerald-600" />
                <span className="text-sm text-slate-700">{form[c.name] ? 'Да' : 'Нет'}</span>
              </span>
            ) : c.fk_table ? (
              <FkSelect table={c.fk_table} value={String(form[c.name] ?? '')} className="input h-9 py-1"
                onChange={(v) => setForm((f) => ({ ...f, [c.name]: v }))} />
            ) : c.type === 'text' ? (
              <textarea rows={3} value={String(form[c.name] ?? '')} onChange={(e) => setForm((f) => ({ ...f, [c.name]: e.target.value }))} className="input" />
            ) : (
              <input
                type={c.type === 'date' ? 'date' : c.type === 'datetime' ? 'datetime-local' : 'text'}
                inputMode={c.type === 'integer' || c.type === 'float' ? 'decimal' : undefined}
                maxLength={c.max_length ?? undefined}
                value={String(form[c.name] ?? '')}
                onChange={(e) => setForm((f) => ({ ...f, [c.name]: e.target.value }))}
                className={clsx('input h-9 py-1', (c.type === 'integer' || c.type === 'float') && 'text-right tabular-nums',
                  c.required && String(form[c.name] ?? '') === '' && 'border-red-300')}
              />
            )}
          </label>
        ))}
      </div>
      {mode === 'edit' && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-slate-500">
          <X className="h-3 w-3" /> Очистите поле, чтобы удалить значение. Сохраняются только изменённые поля.
        </p>
      )}
    </Modal>
  )
}
