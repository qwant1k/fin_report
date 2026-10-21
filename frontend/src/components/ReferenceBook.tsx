import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CloudDownload, Plus, Save, Search, X } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { sourceLabel } from '@/lib/displayLabels'
import { apiErrorMessage } from '@/lib/notifications'
import CouponScheduleEditor from '@/components/CouponScheduleEditor'

export type ReferenceIssue = {
  id?: number
  isin: string
  ticker_kase?: string | null
  instrument_name?: string | null
  issuer?: string | null
  bond_type?: string | null
  coupon_type?: string | null
  float_index?: string | null
  float_margin_pct?: number | string | null
  coupon_rate_pct?: number | null
  coupon_rate_text?: string | null
  frequency?: number | null
  base?: string | null
  nominal?: number | null
  currency?: string | null
  start_date?: string | null
  maturity_date?: string | null
  source?: string | null
  source_updated_at?: string | null
  coupon_schedule_rows?: number
  notes?: string | null
}

const COUPON_TYPES: Record<string, string> = { fix: 'фиксированный', float: 'плавающий', zero: 'дисконтный' }
const TYPES = ['ГЦБ', 'Агентские', 'МФО', 'Ин.ЦБ']

function fmt(d?: string | null) {
  if (!d) return '—'
  const [y, m, dd] = d.slice(0, 10).split('-')
  return `${dd}.${m}.${y}`
}

/** Справочник выпусков (InstrumentReference): all issues used by the
 *  calculations, including those without a position of a manager. */
export default function ReferenceBook({ canWrite }: { canWrite: boolean }) {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<ReferenceIssue | null>(null)
  const [creating, setCreating] = useState(false)

  const listQ = useQuery<ReferenceIssue[]>({
    queryKey: ['reference-book', search],
    queryFn: async () => (await api.get('/securities/reference', { params: search.trim() ? { search: search.trim() } : {} })).data,
  })

  const syncAll = useMutation({
    mutationFn: async () => (await api.post('/securities/reference/coupons/fetch-kase-all', null, { params: { scope: 'held' } })).data,
    onSuccess: (r) => {
      const failed = Object.keys(r.failed ?? {}).length
      toast.success(`Справочник KASE обновлён: успешно ${Object.keys(r.updated ?? {}).length} из ${r.requested}${failed ? `, с ошибками ${failed}` : ''}.`)
      qc.invalidateQueries({ queryKey: ['reference-book'] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось обновить справочник выпусков с KASE')),
  })

  const rows = listQ.data ?? []
  return (
    <div className="space-y-3">
      <section className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2">
        <label className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input className="input-sm w-80 pl-9" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="ISIN, тикер, наименование, эмитент" />
        </label>
        {canWrite && (
          <div className="flex flex-wrap gap-2">
            <button className="btn-secondary" disabled={syncAll.isPending} onClick={() => syncAll.mutate()}
              title="Загрузить параметры и графики купонов с kase.kz для бумаг, которые есть в портфелях">
              <CloudDownload className={`h-4 w-4 ${syncAll.isPending ? 'animate-pulse' : ''}`} /> Обновить с KASE (бумаги в портфелях)
            </button>
            <button className="btn-primary" onClick={() => { setCreating(true); setSelected({ isin: '', currency: 'KZT', base: '30/360' }) }}>
              <Plus className="h-4 w-4" /> Новый выпуск
            </button>
          </div>
        )}
      </section>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <div className="overflow-hidden rounded-lg border border-slate-300 bg-white">
          <div className="max-h-[75vh] overflow-auto">
            <table className="detail-table">
              <thead className="sticky top-0 z-10">
                <tr><th>ISIN</th><th>Тикер</th><th>Эмитент / наименование</th><th>Купон</th><th>Погашение</th><th className="text-right">График</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.isin} onClick={() => { setCreating(false); setSelected(r) }}
                    className={`cursor-pointer ${selected?.isin === r.isin ? '[&>td]:!bg-emerald-100 [&>td]:font-semibold' : ''}`}>
                    <td className="font-mono">{r.isin}</td>
                    <td className="font-mono">{r.ticker_kase ?? '—'}</td>
                    <td><div className="max-w-64 truncate font-medium text-slate-900">{r.issuer ?? '—'}</div><div className="max-w-64 truncate text-[11px] text-slate-600">{r.instrument_name}</div></td>
                    <td>{r.coupon_type === 'zero' ? 'дисконт' : r.coupon_rate_pct != null ? `${r.coupon_rate_pct}%` : '—'}{r.coupon_type === 'float' && <span className="ml-1 rounded bg-amber-100 px-1 text-amber-800">плав.</span>}</td>
                    <td className="whitespace-nowrap">{fmt(r.maturity_date)}{r.maturity_date && r.maturity_date < new Date().toISOString().slice(0, 10) && <span className="ml-1 rounded bg-slate-200 px-1 text-[11px] text-slate-700" title="Срок погашения прошёл: бумага не входит в стоимость портфелей">погашен</span>}</td>
                    <td className="num">{r.coupon_schedule_rows ? r.coupon_schedule_rows : <span className="text-slate-400">нет</span>}</td>
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={6} className="py-8 text-center text-slate-400">{listQ.isLoading ? 'Загрузка…' : 'Выпусков не найдено'}</td></tr>}
              </tbody>
            </table>
          </div>
        </div>

        <div>
          {selected ? (
            <IssueEditor key={(creating ? 'new' : selected.isin)} issue={selected} isNew={creating} canWrite={canWrite}
              onClose={() => { setSelected(null); setCreating(false) }}
              onSaved={(r) => { setCreating(false); setSelected(r); qc.invalidateQueries({ queryKey: ['reference-book'] }) }} />
          ) : (
            <div className="flex h-full min-h-48 items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">
              Выберите выпуск слева, чтобы открыть его параметры и график купонных выплат
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export function IssueEditor({ issue, isNew, canWrite, onClose, onSaved }: { issue: ReferenceIssue; isNew: boolean; canWrite: boolean; onClose: () => void; onSaved: (r: ReferenceIssue) => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState<ReferenceIssue>(issue)
  useEffect(() => setForm(issue), [issue])
  const set = (k: keyof ReferenceIssue, v: any) => setForm((f) => ({ ...f, [k]: v === '' ? null : v }))

  const save = useMutation({
    mutationFn: async () => (await api.post('/securities/reference', {
      ...form,
      isin: (form.isin || '').trim().toUpperCase(),
      frequency: form.frequency ? Number(form.frequency) : null,
      coupon_rate_pct: form.coupon_rate_pct != null ? Number(form.coupon_rate_pct) : null,
      nominal: form.nominal != null ? Number(form.nominal) : null,
    })).data,
    onSuccess: (r) => { toast.success(`Параметры выпуска ${r.ticker_kase || r.isin || ''} сохранены.`); onSaved({ ...form, ...r }) },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось сохранить параметры выпуска')),
  })
  const fromKase = useMutation({
    mutationFn: async () => (await api.post(`/securities/reference/${encodeURIComponent(form.ticker_kase || form.isin)}/coupons/fetch-kase`)).data,
    onSuccess: (r) => {
      const payments = Number(r.rows_count ?? (Array.isArray(r.rows) ? r.rows.length : r.rows ?? 0))
      toast.success(`График выплат для выпуска «${r.code}» обновлён с KASE: в графике ${payments} выплат. Ручные строки не изменены.`)
      qc.invalidateQueries({ queryKey: ['coupon-schedule'] })
      qc.invalidateQueries({ queryKey: ['reference-book'] })
      if (r.reference) onSaved(r.reference)
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось загрузить график выплат с KASE')),
  })

  const field = (label: string, key: keyof ReferenceIssue, type: 'text' | 'number' | 'date' = 'text') => (
    <label className="block">
      <span className="field-label">{label}</span>
      <input className="input-sm" type={type} step="any" disabled={!canWrite}
        value={(form[key] as any) ?? ''} onChange={(e) => set(key, e.target.value)} />
    </label>
  )

  return (
    <div className="space-y-3 rounded-lg border border-slate-300 bg-white p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-base font-bold text-slate-900">{isNew ? 'Новый выпуск' : `${form.isin}${form.instrument_name ? ` — ${form.instrument_name}` : ''}`}</div>
          <div className="text-xs text-slate-600">
            {form.ticker_kase ?? ''} {form.source ? `· источник: ${sourceLabel(form.source)}` : ''}
            {form.source_updated_at ? ` · обновлено ${fmt(form.source_updated_at)}` : ''}
          </div>
        </div>
        <div className="flex gap-2">
          {canWrite && !isNew && (
            <button className="btn-secondary h-8 px-2 text-xs" onClick={() => fromKase.mutate()} disabled={fromKase.isPending}
              title="Загрузить параметры выпуска и график купонов с kase.kz (ручные правки графика сохраняются)">
              <CloudDownload className={`h-3.5 w-3.5 ${fromKase.isPending ? 'animate-pulse' : ''}`} /> Загрузить с KASE
            </button>
          )}
          <button className="text-slate-400 hover:text-slate-700" onClick={onClose}><X className="h-5 w-5" /></button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-3 gap-y-2 md:grid-cols-3 2xl:grid-cols-4">
        {field('ISIN *', 'isin')}
        {field('Тикер KASE', 'ticker_kase')}
        {field('Наименование', 'instrument_name')}
        {field('Эмитент', 'issuer')}
        <label className="block">
          <span className="field-label">Тип (категория)</span>
          <select className="input-sm" disabled={!canWrite} value={form.bond_type ?? ''} onChange={(e) => set('bond_type', e.target.value)}>
            <option value="">— по эмитенту/тикеру —</option>
            {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="field-label">Вид купона</span>
          <select className="input-sm" disabled={!canWrite} value={form.coupon_type ?? ''} onChange={(e) => set('coupon_type', e.target.value)}>
            <option value="">—</option>
            {Object.entries(COUPON_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        {field('Купон, % годовых (текущий)', 'coupon_rate_pct', 'number')}
        {(form.coupon_type === 'float' || form.float_index) && (
          <label className="block">
            <span className="field-label">Индикатор плавающей ставки</span>
            <select className="input-sm" disabled={!canWrite} value={form.float_index ?? ''} onChange={(e) => set('float_index', e.target.value)}>
              <option value="">— не задан —</option>
              {['TCR_1M', 'TCR_3M', 'TCR_6M'].map((t) => <option key={t} value={t}>{t} (TONIA Compounded)</option>)}
            </select>
          </label>
        )}
        {(form.coupon_type === 'float' || form.float_index) && field('Маржа к индикатору, %', 'float_margin_pct', 'number')}
        <label className="block">
          <span className="field-label">Выплат в год</span>
          <select className="input-sm" disabled={!canWrite} value={form.frequency ?? ''} onChange={(e) => set('frequency', e.target.value)}>
            <option value="">—</option>
            {[1, 2, 4, 12].map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="field-label">Расчётный базис</span>
          <select className="input-sm" disabled={!canWrite} value={form.base ?? ''} onChange={(e) => set('base', e.target.value)}>
            <option value="">—</option>
            {['30/360', 'act/360', 'act/365', 'act/act'].map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </label>
        {field('Номинал', 'nominal', 'number')}
        {field('Валюта', 'currency')}
        {field('Начало обращения', 'start_date', 'date')}
        {field('Дата погашения', 'maturity_date', 'date')}
      </div>
      {canWrite && (
        <div className="flex justify-end">
          <button className="btn-primary h-8 px-3 text-xs" onClick={() => save.mutate()} disabled={save.isPending || !form.isin}>
            <Save className="h-4 w-4" /> Сохранить параметры
          </button>
        </div>
      )}

      {!isNew && form.isin && <CouponScheduleEditor isin={form.isin} canEdit={canWrite} />}
    </div>
  )
}
