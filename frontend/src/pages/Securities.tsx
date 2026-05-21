import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BookMarked,
  Filter,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { CDU } from '@/lib/types'
import { useAuthStore } from '@/lib/auth'

// ─────────────── types ───────────────

interface Holding {
  id: number
  cdu_id: number
  cdu_name: string | null
  isin: string
  instrument_code: string | null
  instrument_name: string | null
  category: string | null
  currency: string
  quantity: number
  avg_purchase_price: number | null
  last_kase_price: number | null
  last_kase_date: string | null
  market_value: number | null
  nominal_per_unit: number | null
  coupon_rate_pct: number | null
  maturity_date: string | null
  source: 'AUTO' | 'MANUAL'
  notes: string | null
  last_synced_at: string | null
  updated_at: string | null
  updated_by: string | null
}

interface Summary {
  total_count: number
  total_market_value: number
  auto_count: number
  manual_count: number
  by_category: Array<{ category: string; count: number; market_value: number }>
}

const CATEGORY_LABEL: Record<string, string> = {
  GOV_BONDS: 'Гос. облигации',
  AGENCY_BONDS: 'Квазигос',
  MFO_BONDS: 'МФО',
  FOREIGN_BONDS: 'Иностранные',
  REVERSE_REPO: 'REPO',
  DEPOSIT: 'Депозиты',
  CASH: 'Денежные средства',
  OTHER: 'Прочее',
}

const CATEGORY_COLOR: Record<string, string> = {
  GOV_BONDS:     'bg-emerald-100 text-emerald-800 ring-emerald-200',
  AGENCY_BONDS:  'bg-cyan-100 text-cyan-800 ring-cyan-200',
  MFO_BONDS:     'bg-indigo-100 text-indigo-800 ring-indigo-200',
  FOREIGN_BONDS: 'bg-violet-100 text-violet-800 ring-violet-200',
  REVERSE_REPO:  'bg-amber-100 text-amber-800 ring-amber-200',
  DEPOSIT:       'bg-blue-100 text-blue-800 ring-blue-200',
  CASH:          'bg-slate-100 text-slate-700 ring-slate-200',
  OTHER:         'bg-slate-100 text-slate-700 ring-slate-200',
}

function formatNumber(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return '—'
  return new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n)
}

function formatMillions(n: number | null | undefined): string {
  if (n == null) return '—'
  return formatNumber(n / 1_000_000, 1) + ' млн'
}

// ─────────────── page ───────────────

export default function SecuritiesPage() {
  const qc = useQueryClient()
  const canWrite = useAuthStore((s) => s.canWrite())

  const [cduFilter, setCduFilter] = useState<number | ''>('')
  const [categoryFilter, setCategoryFilter] = useState<string>('')
  const [sourceFilter, setSourceFilter] = useState<'' | 'AUTO' | 'MANUAL'>('')
  const [onlyWithQty, setOnlyWithQty] = useState(true)
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<Holding | null>(null)
  const [creating, setCreating] = useState(false)

  const cdusQ = useQuery<CDU[]>({
    queryKey: ['cdus'],
    queryFn: async () => (await api.get('/settings/cdus')).data,
  })

  const params = useMemo(() => {
    const p: Record<string, string | number | boolean> = {}
    if (cduFilter) p.cdu_id = cduFilter
    if (categoryFilter) p.category = categoryFilter
    if (sourceFilter) p.source = sourceFilter
    if (search.trim()) p.search = search.trim()
    if (onlyWithQty) p.only_with_qty = true
    return p
  }, [cduFilter, categoryFilter, sourceFilter, search, onlyWithQty])

  const listQ = useQuery<Holding[]>({
    queryKey: ['securities', params],
    queryFn: async () => (await api.get('/securities/', { params })).data,
  })

  const summaryQ = useQuery<Summary>({
    queryKey: ['securities-summary'],
    queryFn: async () => (await api.get('/securities/summary')).data,
  })

  const sync = useMutation({
    mutationFn: async () => (await api.post('/securities/sync')).data,
    onSuccess: (data) => {
      toast.success(
        `Синхронизация: +${data.upserted}, −${data.deleted}, ↻ ${data.manual_refreshed}`,
      )
      qc.invalidateQueries({ queryKey: ['securities'] })
      qc.invalidateQueries({ queryKey: ['securities-summary'] })
    },
    onError: () => toast.error('Не удалось синхронизировать справочник'),
  })

  const remove = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/securities/${id}`)).data,
    onSuccess: () => {
      toast.success('Запись удалена')
      qc.invalidateQueries({ queryKey: ['securities'] })
      qc.invalidateQueries({ queryKey: ['securities-summary'] })
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      toast.error(detail?.message ?? 'Не удалось удалить запись')
    },
  })

  const totalMV = summaryQ.data?.total_market_value ?? 0
  const list = listQ.data ?? []
  const totalShownMV = list.reduce((s, h) => s + (h.market_value ?? 0), 0)

  const resetFilters = () => {
    setCduFilter('')
    setCategoryFilter('')
    setSourceFilter('')
    setSearch('')
    setOnlyWithQty(true)
  }

  const closeModal = () => {
    setEditing(null)
    setCreating(false)
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <BookMarked className="h-6 w-6 text-emerald-600" />
            Справочник ценных бумаг
          </h1>
          <p className="text-sm text-slate-500">
            Агрегат активных позиций по ЧДУ. Обновляется автоматически после загрузки TradeReport.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {canWrite && (
            <>
              <button
                onClick={() => sync.mutate()}
                disabled={sync.isPending}
                className="btn-secondary"
                title="Полная пересборка из активных Trade-записей"
              >
                <RefreshCw className={`h-4 w-4 ${sync.isPending ? 'animate-spin' : ''}`} />
                Синхронизировать
              </button>
              <button onClick={() => setCreating(true)} className="btn-primary">
                <Plus className="h-4 w-4" /> Добавить вручную
              </button>
            </>
          )}
        </div>
      </header>

      {/* ── KPI cards ── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <KpiCard
          label="Всего записей"
          value={summaryQ.data?.total_count ?? 0}
          subtitle={`${summaryQ.data?.auto_count ?? 0} авто · ${summaryQ.data?.manual_count ?? 0} ручных`}
        />
        <KpiCard
          label="Общая рыночная стоимость"
          value={formatMillions(totalMV)}
          subtitle="по последним ценам KASE"
          highlight
        />
        <KpiCard
          label="Показано"
          value={list.length}
          subtitle={formatMillions(totalShownMV)}
        />
        <KpiCard
          label="Категорий"
          value={summaryQ.data?.by_category.length ?? 0}
          subtitle="распределение портфеля"
        />
      </div>

      {/* ── Category chips ── */}
      {summaryQ.data && summaryQ.data.by_category.length > 0 && (
        <div className="card p-4">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
            По категориям
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setCategoryFilter('')}
              className={`rounded-full px-3 py-1 text-xs font-medium ring-1 transition ${
                categoryFilter === ''
                  ? 'bg-emerald-600 text-white ring-emerald-600'
                  : 'bg-white text-slate-700 ring-slate-200 hover:bg-slate-50'
              }`}
            >
              Все
            </button>
            {summaryQ.data.by_category.map((c) => (
              <button
                key={c.category}
                onClick={() => setCategoryFilter(c.category)}
                className={`rounded-full px-3 py-1 text-xs font-medium ring-1 transition ${
                  categoryFilter === c.category
                    ? 'bg-emerald-600 text-white ring-emerald-600'
                    : `${CATEGORY_COLOR[c.category] ?? CATEGORY_COLOR.OTHER} hover:opacity-80`
                }`}
              >
                {CATEGORY_LABEL[c.category] ?? c.category}
                <span className="ml-1.5 opacity-70">· {c.count}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── Filters ── */}
      <div className="card p-4">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
          <Filter className="h-3.5 w-3.5" /> Фильтры
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
          <div className="md:col-span-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="ISIN, тикер или название…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="input pl-9"
              />
            </div>
          </div>
          <select
            className="input"
            value={cduFilter}
            onChange={(e) => setCduFilter(e.target.value ? Number(e.target.value) : '')}
          >
            <option value="">Все ЧДУ</option>
            {cdusQ.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.short_name} — {c.name}
              </option>
            ))}
          </select>
          <select
            className="input"
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value as any)}
          >
            <option value="">Все источники</option>
            <option value="AUTO">Авто (из Trade)</option>
            <option value="MANUAL">Ручные</option>
          </select>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={onlyWithQty}
              onChange={(e) => setOnlyWithQty(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
            />
            Только с qty &gt; 0
          </label>
        </div>
        {(cduFilter || categoryFilter || sourceFilter || search || !onlyWithQty) && (
          <button
            onClick={resetFilters}
            className="mt-2 text-xs font-medium text-slate-500 underline-offset-2 hover:text-emerald-700 hover:underline"
          >
            Сбросить фильтры
          </button>
        )}
      </div>

      {/* ── Table ── */}
      <div className="card overflow-hidden">
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>Категория</th>
                <th>ISIN / Тикер</th>
                <th>Название</th>
                <th>ЧДУ</th>
                <th className="text-right">Количество</th>
                <th className="text-right">Цена покупки</th>
                <th className="text-right">Цена KASE</th>
                <th className="text-right">Рыночная стоимость</th>
                <th>Источник</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {list.map((h) => (
                <HoldingRow
                  key={h.id}
                  h={h}
                  canWrite={canWrite}
                  onEdit={() => setEditing(h)}
                  onDelete={() => {
                    if (confirm(`Удалить запись ${h.isin}?`)) remove.mutate(h.id)
                  }}
                />
              ))}
              {list.length === 0 && (
                <tr>
                  <td colSpan={10} className="py-10 text-center text-slate-400">
                    {listQ.isLoading ? 'Загрузка…' : 'Записей не найдено'}
                  </td>
                </tr>
              )}
            </tbody>
            {list.length > 0 && (
              <tfoot>
                <tr className="bg-slate-50 font-semibold">
                  <td colSpan={7} className="text-right">Итого по показанным:</td>
                  <td className="text-right">{formatMillions(totalShownMV)}</td>
                  <td colSpan={2}></td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </div>

      {/* ── Edit / Create modal ── */}
      {(creating || editing) && (
        <HoldingFormModal
          existing={editing}
          cdus={cdusQ.data ?? []}
          onClose={closeModal}
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ['securities'] })
            qc.invalidateQueries({ queryKey: ['securities-summary'] })
            closeModal()
          }}
        />
      )}
    </div>
  )
}

// ─────────────── KPI card ───────────────

function KpiCard({
  label, value, subtitle, highlight,
}: { label: string; value: string | number; subtitle?: string; highlight?: boolean }) {
  return (
    <div
      className={`card p-4 ${
        highlight ? 'border-emerald-200 bg-emerald-50/70' : ''
      }`}
    >
      <div className="text-xs font-medium uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${highlight ? 'text-emerald-700' : 'text-slate-900'}`}>
        {value}
      </div>
      {subtitle && <div className="mt-0.5 text-xs text-slate-500">{subtitle}</div>}
    </div>
  )
}

// ─────────────── Table row ───────────────

function HoldingRow({
  h, canWrite, onEdit, onDelete,
}: {
  h: Holding; canWrite: boolean; onEdit: () => void; onDelete: () => void
}) {
  const catColor = CATEGORY_COLOR[h.category ?? 'OTHER'] ?? CATEGORY_COLOR.OTHER
  return (
    <tr className="hover:bg-emerald-50/40">
      <td>
        <span className={`inline-flex rounded-md px-2 py-0.5 text-xs font-medium ring-1 ${catColor}`}>
          {CATEGORY_LABEL[h.category ?? 'OTHER'] ?? '—'}
        </span>
      </td>
      <td className="font-mono text-xs">
        <div className="font-semibold">{h.isin}</div>
        {h.instrument_code && (
          <div className="text-slate-500">{h.instrument_code}</div>
        )}
      </td>
      <td className="max-w-xs truncate" title={h.instrument_name ?? ''}>
        {h.instrument_name ?? '—'}
      </td>
      <td className="whitespace-nowrap">{h.cdu_name ?? `#${h.cdu_id}`}</td>
      <td className="text-right font-mono">{formatNumber(h.quantity, 0)}</td>
      <td className="text-right font-mono text-slate-600">
        {formatNumber(h.avg_purchase_price, 4)}
      </td>
      <td className="text-right font-mono">
        <div>{formatNumber(h.last_kase_price, 4)}</div>
        {h.last_kase_date && (
          <div className="text-[10px] text-slate-400">{h.last_kase_date}</div>
        )}
      </td>
      <td className="text-right font-mono font-semibold">
        {formatMillions(h.market_value)}
      </td>
      <td>
        {h.source === 'MANUAL' ? (
          <span className="inline-flex rounded-md bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-amber-200">
            Ручной
          </span>
        ) : (
          <span className="inline-flex rounded-md bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-600 ring-1 ring-slate-200">
            Авто
          </span>
        )}
      </td>
      <td className="text-right">
        {canWrite && (
          <div className="flex justify-end gap-1">
            <button
              onClick={onEdit}
              className="rounded p-1.5 text-slate-500 hover:bg-slate-100 hover:text-emerald-700"
              title="Редактировать"
            >
              <Pencil className="h-4 w-4" />
            </button>
            {h.source === 'MANUAL' && (
              <button
                onClick={onDelete}
                className="rounded p-1.5 text-slate-500 hover:bg-red-50 hover:text-red-600"
                title="Удалить (только ручные)"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        )}
      </td>
    </tr>
  )
}

// ─────────────── Create / Edit modal ───────────────

interface FormState {
  cdu_id: number | ''
  isin: string
  instrument_code: string
  instrument_name: string
  category: string
  currency: string
  quantity: string
  avg_purchase_price: string
  last_kase_price: string
  nominal_per_unit: string
  coupon_rate_pct: string
  maturity_date: string
  notes: string
}

function emptyForm(): FormState {
  return {
    cdu_id: '',
    isin: '',
    instrument_code: '',
    instrument_name: '',
    category: 'GOV_BONDS',
    currency: 'KZT',
    quantity: '',
    avg_purchase_price: '',
    last_kase_price: '',
    nominal_per_unit: '',
    coupon_rate_pct: '',
    maturity_date: '',
    notes: '',
  }
}

function HoldingFormModal({
  existing, cdus, onClose, onSaved,
}: {
  existing: Holding | null
  cdus: CDU[]
  onClose: () => void
  onSaved: () => void
}) {
  const isEdit = !!existing
  const isAutoEdit = existing?.source === 'AUTO'
  const [form, setForm] = useState<FormState>(() => {
    if (!existing) return emptyForm()
    return {
      cdu_id: existing.cdu_id,
      isin: existing.isin,
      instrument_code: existing.instrument_code ?? '',
      instrument_name: existing.instrument_name ?? '',
      category: existing.category ?? 'GOV_BONDS',
      currency: existing.currency,
      quantity: existing.quantity?.toString() ?? '',
      avg_purchase_price: existing.avg_purchase_price?.toString() ?? '',
      last_kase_price: existing.last_kase_price?.toString() ?? '',
      nominal_per_unit: existing.nominal_per_unit?.toString() ?? '',
      coupon_rate_pct: existing.coupon_rate_pct?.toString() ?? '',
      maturity_date: existing.maturity_date ?? '',
      notes: existing.notes ?? '',
    }
  })

  const save = useMutation({
    mutationFn: async () => {
      const num = (s: string) => (s.trim() === '' ? null : Number(s))
      const payload: Record<string, unknown> = {
        cdu_id: form.cdu_id || undefined,
        isin: form.isin.trim().toUpperCase(),
        instrument_code: form.instrument_code.trim() || null,
        instrument_name: form.instrument_name.trim() || null,
        category: form.category || null,
        currency: form.currency || 'KZT',
        quantity: num(form.quantity),
        avg_purchase_price: num(form.avg_purchase_price),
        last_kase_price: num(form.last_kase_price),
        nominal_per_unit: num(form.nominal_per_unit),
        coupon_rate_pct: num(form.coupon_rate_pct),
        maturity_date: form.maturity_date || null,
        notes: form.notes.trim() || null,
      }
      if (isEdit) {
        return (await api.patch(`/securities/${existing!.id}`, payload)).data
      }
      return (await api.post('/securities/', payload)).data
    },
    onSuccess: () => {
      toast.success(isEdit ? 'Запись обновлена' : 'Запись добавлена')
      onSaved()
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      toast.error(detail?.message ?? detail ?? 'Не удалось сохранить запись')
    },
  })

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setForm((f) => ({ ...f, [k]: v }))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="card w-full max-w-2xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-200 p-4">
          <h2 className="text-lg font-semibold">
            {isEdit ? `Редактирование: ${existing!.isin}` : 'Новая запись справочника'}
          </h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-4 p-5">
          {isAutoEdit && (
            <div className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200">
              Это запись из автосинхронизации. Поля <b>Количество</b> и{' '}
              <b>Средняя цена покупки</b> пересчитываются из Trade-данных и не редактируются здесь.
            </div>
          )}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="ЧДУ" required>
              <select
                className="input"
                value={form.cdu_id}
                onChange={(e) => set('cdu_id', e.target.value ? Number(e.target.value) : '')}
                disabled={isEdit}
              >
                <option value="">— выберите —</option>
                {cdus.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.short_name} — {c.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="ISIN" required>
              <input
                className="input font-mono uppercase"
                value={form.isin}
                onChange={(e) => set('isin', e.target.value.toUpperCase())}
                placeholder="KZ0001234567"
                disabled={isEdit}
              />
            </Field>
            <Field label="Тикер">
              <input
                className="input font-mono"
                value={form.instrument_code}
                onChange={(e) => set('instrument_code', e.target.value)}
                placeholder="MOM_b1"
              />
            </Field>
            <Field label="Категория">
              <select
                className="input"
                value={form.category}
                onChange={(e) => set('category', e.target.value)}
              >
                {Object.entries(CATEGORY_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </Field>
            <Field label="Название" className="sm:col-span-2">
              <input
                className="input"
                value={form.instrument_name}
                onChange={(e) => set('instrument_name', e.target.value)}
                placeholder="Облигация Министерства финансов РК"
              />
            </Field>
            <Field label="Количество">
              <input
                type="number"
                step="any"
                className="input text-right"
                value={form.quantity}
                onChange={(e) => set('quantity', e.target.value)}
                disabled={isAutoEdit}
              />
            </Field>
            <Field label="Средняя цена покупки">
              <input
                type="number"
                step="any"
                className="input text-right"
                value={form.avg_purchase_price}
                onChange={(e) => set('avg_purchase_price', e.target.value)}
                disabled={isAutoEdit}
              />
            </Field>
            <Field label="Цена KASE (для расчёта стоимости)">
              <input
                type="number"
                step="any"
                className="input text-right"
                value={form.last_kase_price}
                onChange={(e) => set('last_kase_price', e.target.value)}
              />
            </Field>
            <Field label="Валюта">
              <input
                className="input uppercase"
                value={form.currency}
                onChange={(e) => set('currency', e.target.value.toUpperCase())}
              />
            </Field>
            <Field label="Номинал на ед.">
              <input
                type="number"
                step="any"
                className="input text-right"
                value={form.nominal_per_unit}
                onChange={(e) => set('nominal_per_unit', e.target.value)}
              />
            </Field>
            <Field label="Купон (%)">
              <input
                type="number"
                step="any"
                className="input text-right"
                value={form.coupon_rate_pct}
                onChange={(e) => set('coupon_rate_pct', e.target.value)}
              />
            </Field>
            <Field label="Дата погашения">
              <input
                type="date"
                className="input"
                value={form.maturity_date}
                onChange={(e) => set('maturity_date', e.target.value)}
              />
            </Field>
            <Field label="Заметки" className="sm:col-span-2">
              <textarea
                className="input min-h-[60px]"
                value={form.notes}
                onChange={(e) => set('notes', e.target.value)}
              />
            </Field>
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-200 p-4">
          <button onClick={onClose} className="btn-secondary">Отменить</button>
          <button
            onClick={() => save.mutate()}
            disabled={save.isPending || !form.cdu_id || !form.isin.trim()}
            className="btn-primary"
          >
            {save.isPending ? 'Сохранение…' : 'Сохранить'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({
  label, required, children, className,
}: {
  label: string; required?: boolean; children: React.ReactNode; className?: string
}) {
  return (
    <div className={className}>
      <label className="mb-1 block text-xs font-medium text-slate-600">
        {label} {required && <span className="text-red-500">*</span>}
      </label>
      {children}
    </div>
  )
}
