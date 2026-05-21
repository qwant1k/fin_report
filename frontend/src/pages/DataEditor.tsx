import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  ChevronDown,
  ChevronRight,
  Database,
  Edit3,
  Filter,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  Search,
  Table2,
  Trash2,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

// ─────────────── types ───────────────

interface TableInfo {
  name: string
  label: string
}

interface ColumnMeta {
  name: string
  type: 'string' | 'integer' | 'float' | 'boolean' | 'date' | 'datetime' | 'text'
  nullable: boolean
  default: string | null
}

interface TableMeta {
  name: string
  label: string
  columns: ColumnMeta[]
}

interface ListResponse {
  data: Array<Record<string, unknown>>
  total: number
  page: number
  page_size: number
}

// ─────────────── helpers ───────────────

function formatCell(value: unknown, type: string): string {
  if (value === null || value === undefined) return '—'
  if (type === 'boolean') return value ? 'Да' : 'Нет'
  if (typeof value === 'number') return value.toLocaleString('ru-KZ', { maximumFractionDigits: 4 })
  return String(value)
}

function inputTypeFor(colType: string): string {
  switch (colType) {
    case 'integer':
    case 'float':
      return 'number'
    case 'date':
      return 'date'
    case 'datetime':
      return 'datetime-local'
    case 'boolean':
      return 'checkbox'
    default:
      return 'text'
  }
}

function stepFor(colType: string): string {
  return colType === 'integer' ? '1' : '0.01'
}

function coercePayload(value: unknown, colType: string): unknown {
  if (value === '' || value === null || value === undefined) return null
  if (colType === 'boolean') return Boolean(value)
  if (colType === 'integer') return parseInt(String(value), 10)
  if (colType === 'float') return parseFloat(String(value))
  return value
}

// ─────────────── component ───────────────

export default function DataEditorPage() {
  const queryClient = useQueryClient()
  const role = useAuthStore((s) => s.role)
  const canWrite = useAuthStore((s) => s.canWrite())

  const [selectedTable, setSelectedTable] = useState<string>('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [sortCol, setSortCol] = useState<string>('id')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [columnFilters, setColumnFilters] = useState<Record<string, string>>({})

  const [editingRow, setEditingRow] = useState<Record<string, unknown> | null>(null)
  const [creating, setCreating] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  // Fetch table list
  const tablesQ = useQuery<TableInfo[]>({
    queryKey: ['data-editor', 'tables'],
    queryFn: async () => {
      const { data } = await api.get('/data/tables')
      return data
    },
  })

  // Fetch table metadata
  const metaQ = useQuery<TableMeta | null>({
    queryKey: ['data-editor', 'meta', selectedTable],
    queryFn: async () => {
      if (!selectedTable) return null
      const { data } = await api.get(`/data/tables/${selectedTable}/meta`)
      return data
    },
    enabled: !!selectedTable,
  })

  // Build query params for list
  const listParams = useMemo(() => {
    const params: Record<string, string | number> = {
      page,
      page_size: pageSize,
      sort: sortCol,
      order: sortOrder,
    }
    if (search) params.search = search
    Object.entries(columnFilters).forEach(([k, v]) => {
      if (v) params[k] = v
    })
    return params
  }, [page, pageSize, sortCol, sortOrder, search, columnFilters])

  // Fetch rows
  const rowsQ = useQuery<ListResponse>({
    queryKey: ['data-editor', 'rows', selectedTable, listParams],
    queryFn: async () => {
      if (!selectedTable) return { data: [], total: 0, page: 1, page_size: pageSize }
      const { data } = await api.get(`/data/tables/${selectedTable}`, { params: listParams })
      return data
    },
    enabled: !!selectedTable,
  })

  // Reset page when table/search/filters change
  useEffect(() => {
    setPage(1)
  }, [selectedTable, search, columnFilters])

  // Mutations
  const createM = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      const { data } = await api.post(`/data/tables/${selectedTable}`, payload)
      return data
    },
    onSuccess: () => {
      toast.success('Запись создана')
      setCreating(false)
      queryClient.invalidateQueries({ queryKey: ['data-editor', 'rows', selectedTable] })
    },
    onError: () => toast.error('Ошибка создания'),
  })

  const updateM = useMutation({
    mutationFn: async ({ id, payload }: { id: number; payload: Record<string, unknown> }) => {
      const { data } = await api.patch(`/data/tables/${selectedTable}/${id}`, payload)
      return data
    },
    onSuccess: () => {
      toast.success('Запись обновлена')
      setEditingRow(null)
      queryClient.invalidateQueries({ queryKey: ['data-editor', 'rows', selectedTable] })
    },
    onError: () => toast.error('Ошибка обновления'),
  })

  const deleteM = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/data/tables/${selectedTable}/${id}`)
    },
    onSuccess: () => {
      toast.success('Запись удалена')
      setDeletingId(null)
      queryClient.invalidateQueries({ queryKey: ['data-editor', 'rows', selectedTable] })
    },
    onError: () => toast.error('Ошибка удаления'),
  })

  // Select first table on load
  useEffect(() => {
    if (tablesQ.data && tablesQ.data.length > 0 && !selectedTable) {
      setSelectedTable(tablesQ.data[0].name)
    }
  }, [tablesQ.data, selectedTable])

  const totalPages = Math.ceil((rowsQ.data?.total ?? 0) / pageSize)

  const handleSort = (col: string) => {
    if (sortCol === col) {
      setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortCol(col)
      setSortOrder('asc')
    }
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] gap-4 p-4">
      {/* ─── Sidebar ─── */}
      <aside className="flex w-64 flex-col gap-3 overflow-y-auto rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        <div className="flex items-center gap-2 border-b border-slate-100 pb-2 text-sm font-bold text-slate-700">
          <Database className="h-4 w-4 text-emerald-600" />
          Таблицы
        </div>
        {tablesQ.isLoading && (
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Loader2 className="h-3 w-3 animate-spin" /> Загрузка...
          </div>
        )}
        {tablesQ.data?.map((t) => (
          <button
            key={t.name}
            onClick={() => {
              setSelectedTable(t.name)
              setColumnFilters({})
              setSearch('')
            }}
            className={`flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition ${
              selectedTable === t.name
                ? 'bg-emerald-50 font-semibold text-emerald-700 ring-1 ring-emerald-200'
                : 'text-slate-600 hover:bg-slate-50'
            }`}
          >
            <Table2 className="h-3.5 w-3.5 shrink-0 opacity-60" />
            <span className="truncate">{t.label}</span>
          </button>
        ))}
      </aside>

      {/* ─── Main area ─── */}
      <main className="flex flex-1 flex-col gap-3 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        {/* Toolbar */}
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-4 py-3">
          <div className="text-lg font-bold text-slate-800">
            {metaQ.data?.label ?? selectedTable}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Поиск..."
                className="w-56 rounded-lg border border-slate-200 py-1.5 pl-8 pr-3 text-sm text-slate-700 focus:border-emerald-400 focus:outline-none focus:ring-1 focus:ring-emerald-200"
              />
            </div>
            <button
              onClick={() => rowsQ.refetch()}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
              title="Обновить"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${rowsQ.isFetching ? 'animate-spin' : ''}`} />
            </button>
            {canWrite && (
              <button
                onClick={() => setCreating(true)}
                className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700"
              >
                <Plus className="h-3.5 w-3.5" /> Добавить
              </button>
            )}
          </div>
        </div>

        {/* Column quick-filters */}
        {metaQ.data && (
          <div className="flex flex-wrap gap-2 px-4 pb-2">
            {metaQ.data.columns
              .filter((c) => !['id', 'created_at', 'updated_at', 'sha256', 'file_path', 'raw_file_path', 'password_hash'].includes(c.name))
              .slice(0, 6)
              .map((col) => (
                <div key={col.name} className="flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-2 py-1">
                  <Filter className="h-3 w-3 text-slate-400" />
                  <span className="text-xs text-slate-500">{col.name}</span>
                  <input
                    type="text"
                    value={columnFilters[col.name] ?? ''}
                    onChange={(e) =>
                      setColumnFilters((prev) => ({ ...prev, [col.name]: e.target.value }))
                    }
                    className="w-24 border-0 bg-transparent p-0 text-xs text-slate-700 focus:ring-0"
                    placeholder="..."
                  />
                </div>
              ))}
            {Object.keys(columnFilters).length > 0 && (
              <button
                onClick={() => setColumnFilters({})}
                className="rounded-md px-2 py-1 text-xs text-red-500 hover:bg-red-50"
              >
                Сбросить фильтры
              </button>
            )}
          </div>
        )}

        {/* Data grid */}
        <div className="flex-1 overflow-auto px-4 pb-4">
          {rowsQ.isLoading ? (
            <div className="flex h-64 items-center justify-center gap-2 text-slate-400">
              <Loader2 className="h-5 w-5 animate-spin" /> Загрузка...
            </div>
          ) : rowsQ.data && rowsQ.data.data.length === 0 ? (
            <div className="flex h-64 flex-col items-center justify-center gap-2 text-slate-400">
              <Database className="h-8 w-8 opacity-30" />
              <span className="text-sm">Нет данных</span>
            </div>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 z-10 bg-slate-50 text-slate-500">
                <tr>
                  <th className="px-2 py-2 font-semibold">#</th>
                  {metaQ.data?.columns.map((col) => (
                    <th
                      key={col.name}
                      onClick={() => handleSort(col.name)}
                      className="cursor-pointer whitespace-nowrap px-2 py-2 font-semibold hover:text-slate-700"
                    >
                      <div className="flex items-center gap-1">
                        {col.name}
                        {sortCol === col.name &&
                          (sortOrder === 'asc' ? (
                            <ChevronRight className="h-3 w-3 rotate-[-90deg]" />
                          ) : (
                            <ChevronDown className="h-3 w-3" />
                          ))}
                      </div>
                    </th>
                  ))}
                  {canWrite && <th className="px-2 py-2 font-semibold">Действия</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rowsQ.data?.data.map((row) => (
                  <tr key={String(row.id)} className="hover:bg-slate-50">
                    <td className="px-2 py-2 font-mono text-slate-400">{String(row.id)}</td>
                    {metaQ.data?.columns.map((col) => {
                      const val = row[col.name]
                      return (
                        <td key={col.name} className="px-2 py-2 text-slate-700">
                          <span
                            className={`${
                              val === null || val === undefined ? 'text-slate-300' : ''
                            } ${col.type === 'boolean' ? 'font-medium' : ''} ${col.type === 'float' || col.type === 'integer' ? 'font-mono' : ''}`}
                          >
                            {formatCell(val, col.type)}
                          </span>
                        </td>
                      )
                    })}
                    {canWrite && (
                      <td className="px-2 py-2">
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => setEditingRow(row)}
                            className="rounded p-1 text-slate-400 hover:bg-emerald-50 hover:text-emerald-600"
                            title="Редактировать"
                          >
                            <Edit3 className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => setDeletingId(Number(row.id))}
                            className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
                            title="Удалить"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {rowsQ.data && rowsQ.data.total > 0 && (
          <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3">
            <div className="text-xs text-slate-500">
              {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, rowsQ.data.total)} из{' '}
              {rowsQ.data.total}
            </div>
            <div className="flex items-center gap-2">
              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value))
                  setPage(1)
                }}
                className="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-600"
              >
                <option value={20}>20</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
                <option value={200}>200</option>
                <option value={500}>500</option>
              </select>
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="rounded-lg border border-slate-200 p-1 text-slate-600 hover:bg-slate-50 disabled:opacity-40"
              >
                <ArrowLeft className="h-3.5 w-3.5" />
              </button>
              <span className="text-xs text-slate-600">
                Стр. {page} / {totalPages || 1}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="rounded-lg border border-slate-200 p-1 text-slate-600 hover:bg-slate-50 disabled:opacity-40"
              >
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}
      </main>

      {/* ─── Create Modal ─── */}
      {creating && metaQ.data && (
        <RowModal
          mode="create"
          meta={metaQ.data}
          initialData={{}}
          onClose={() => setCreating(false)}
          onSubmit={(payload) => createM.mutate(payload)}
          isLoading={createM.isPending}
        />
      )}

      {/* ─── Edit Modal ─── */}
      {editingRow && metaQ.data && (
        <RowModal
          mode="edit"
          meta={metaQ.data}
          initialData={editingRow}
          onClose={() => setEditingRow(null)}
          onSubmit={(payload) =>
            updateM.mutate({ id: Number(editingRow.id as number), payload })
          }
          isLoading={updateM.isPending}
        />
      )}

      {/* ─── Delete Confirm ─── */}
      {deletingId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-xl bg-white p-5 shadow-xl">
            <div className="mb-3 flex items-center gap-2 text-red-600">
              <AlertTriangle className="h-5 w-5" />
              <h3 className="font-bold">Удалить запись?</h3>
            </div>
            <p className="mb-4 text-sm text-slate-600">
              Запись <span className="font-mono font-bold">id={deletingId}</span> будет удалена безвозвратно.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setDeletingId(null)}
                className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50"
              >
                Отмена
              </button>
              <button
                onClick={() => deleteM.mutate(deletingId)}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
              >
                Удалить
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─────────────── Row Modal (create / edit) ───────────────

function RowModal({
  mode,
  meta,
  initialData,
  onClose,
  onSubmit,
  isLoading,
}: {
  mode: 'create' | 'edit'
  meta: TableMeta
  initialData: Record<string, unknown>
  onClose: () => void
  onSubmit: (payload: Record<string, unknown>) => void
  isLoading: boolean
}) {
  const [form, setForm] = useState<Record<string, unknown>>({})

  useEffect(() => {
    const init: Record<string, unknown> = {}
    meta.columns.forEach((col) => {
      if (mode === 'edit') {
        init[col.name] = initialData[col.name] ?? null
      } else {
        init[col.name] = col.default ?? null
      }
    })
    setForm(init)
  }, [meta, initialData, mode])

  const handleChange = (name: string, type: string, value: unknown) => {
    setForm((prev) => ({ ...prev, [name]: coercePayload(value, type) }))
  }

  const handleSubmit = () => {
    const payload: Record<string, unknown> = {}
    meta.columns.forEach((col) => {
      const v = form[col.name]
      if (v !== undefined && v !== null && v !== '') {
        payload[col.name] = v
      }
    })
    onSubmit(payload)
  }

  const safeValue = (v: unknown, type: string): string | number | boolean => {
    if (v === null || v === undefined) {
      if (type === 'boolean') return false
      return ''
    }
    if (type === 'datetime' && typeof v === 'string') {
      // datetime-local expects YYYY-MM-DDTHH:MM
      return v.slice(0, 16)
    }
    if (type === 'date' && typeof v === 'string') {
      return v.slice(0, 10)
    }
    return v as string | number | boolean
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <h3 className="font-bold text-slate-800">
            {mode === 'create' ? 'Новая запись' : `Редактировать #${String(initialData.id ?? '')}`}
          </h3>
          <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {meta.columns
              .filter((c) => !['created_at', 'updated_at', 'last_synced_at', 'calculated_at', 'fetched_at'].includes(c.name))
              .map((col) => {
                const val = safeValue(form[col.name], col.type)
                return (
                  <div key={col.name} className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-600">
                      {col.name}
                      {!col.nullable && <span className="ml-0.5 text-red-400">*</span>}
                    </label>
                    {col.type === 'text' ? (
                      <textarea
                        value={String(val ?? '')}
                        onChange={(e) => handleChange(col.name, col.type, e.target.value)}
                        rows={3}
                        className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 focus:border-emerald-400 focus:outline-none focus:ring-1 focus:ring-emerald-200"
                      />
                    ) : col.type === 'boolean' ? (
                      <label className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={Boolean(val)}
                          onChange={(e) => handleChange(col.name, col.type, e.target.checked)}
                          className="h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                        />
                        <span className="text-sm text-slate-600">{val ? 'Да' : 'Нет'}</span>
                      </label>
                    ) : (
                      <input
                        type={inputTypeFor(col.type)}
                        step={stepFor(col.type)}
                        value={val as string | number}
                        onChange={(e) =>
                          handleChange(
                            col.name,
                            col.type,
                            col.type === 'boolean' ? e.target.checked : e.target.value,
                          )
                        }
                        className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 focus:border-emerald-400 focus:outline-none focus:ring-1 focus:ring-emerald-200"
                      />
                    )}
                  </div>
                )
              })}
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-3">
          <button
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50"
          >
            Отмена
          </button>
          <button
            onClick={handleSubmit}
            disabled={isLoading}
            className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            {isLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            {mode === 'create' ? 'Создать' : 'Сохранить'}
          </button>
        </div>
      </div>
    </div>
  )
}
