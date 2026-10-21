import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, CloudDownload, Plus, Save, Trash2, Upload, Wand2 } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { sourceLabel } from '@/lib/displayLabels'
import { apiErrorMessage } from '@/lib/notifications'

type Row = {
  seq?: number | null
  period_start?: string | null
  payment_date: string
  record_date?: string | null
  payment_end_date?: string | null
  rate_pct?: number | string | null
  margin_pct?: number | string | null
  index_rate_pct?: number | string | null
  amount_per_unit?: number | string | null
  source?: string
}

const SOURCE_LABEL: Record<string, string> = {
  KASE: 'KASE', MANUAL: 'вручную', IMPORT: 'файл', GENERATED: 'по параметрам',
}

/** «График купонных выплат» of an issue: view, manual edit, import from the
 *  KASE table (XLSX/CSV) and pre-fill from the issue parameters.  Saved rows
 *  are used by the valuation (НКД) and by the coupon automation. */
export default function CouponScheduleEditor({ isin, canEdit }: { isin: string; canEdit: boolean }) {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [rows, setRows] = useState<Row[]>([])
  const [dirty, setDirty] = useState(false)

  const q = useQuery<{ isin: string; rows: Row[] }>({
    queryKey: ['coupon-schedule', isin],
    queryFn: async () => (await api.get(`/securities/reference/${encodeURIComponent(isin)}/coupons`)).data,
  })
  useEffect(() => {
    if (q.data && !dirty) setRows(q.data.rows)
  }, [q.data, dirty])

  const save = useMutation({
    mutationFn: async () => (await api.put(`/securities/reference/${encodeURIComponent(isin)}/coupons`, {
      rows: rows.map((r) => ({ ...r, rate_pct: r.rate_pct === '' ? null : r.rate_pct, amount_per_unit: r.amount_per_unit === '' ? null : r.amount_per_unit })),
    })).data,
    onSuccess: () => {
      toast.success(`График купонов сохранён: выплат ${rows.length}.`)
      setDirty(false)
      qc.invalidateQueries({ queryKey: ['coupon-schedule', isin] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось сохранить график купонов')),
  })
  const generate = useMutation({
    mutationFn: async () => (await api.post(`/securities/reference/${encodeURIComponent(isin)}/coupons/generate`)).data,
    onSuccess: (r) => {
      setRows(r.rows); setDirty(true)
      toast.success('График рассчитан по параметрам выпуска. Проверьте даты и сохраните изменения.')
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось рассчитать график купонов')),
  })
  const fromKase = useMutation({
    mutationFn: async () => (await api.post(`/securities/reference/${encodeURIComponent(isin)}/coupons/fetch-kase`)).data,
    onSuccess: (r) => {
      const payments = Number(r.rows_count ?? (Array.isArray(r.rows) ? r.rows.length : r.rows ?? 0))
      toast.success(`График выплат для выпуска «${r.code}» обновлён с KASE: в графике ${payments} выплат. Ручные строки не изменены.`)
      setDirty(false)
      qc.invalidateQueries({ queryKey: ['coupon-schedule', isin] })
      qc.invalidateQueries({ queryKey: ['reference-book'] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось загрузить график купонов с KASE')),
  })
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData()
      form.append('file', file)
      form.append('isin', isin)
      return (await api.post('/securities/reference/coupons/import', form)).data
    },
    onSuccess: (r) => {
      const n = Object.values(r.imported ?? {}).reduce((a: number, b: any) => a + Number(b), 0)
      toast.success(`График купонов импортирован из файла: выплат ${n}.`)
      setDirty(false)
      qc.invalidateQueries({ queryKey: ['coupon-schedule', isin] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось импортировать график купонов из файла')),
  })

  // an edited or added row becomes MANUAL: a later refresh from KASE keeps it
  const update = (i: number, key: keyof Row, value: string) => {
    setRows((prev) => prev.map((r, idx) => {
      if (idx !== i) return r
      const next: Row = { ...r, [key]: value, source: 'MANUAL' }
      if ((key === 'margin_pct' || key === 'index_rate_pct') && next.margin_pct !== '' && next.index_rate_pct !== ''
        && next.margin_pct != null && next.index_rate_pct != null) {
        next.rate_pct = Math.round((Number(next.margin_pct) + Number(next.index_rate_pct)) * 1e6) / 1e6
      }
      return next
    }))
    setDirty(true)
  }
  const addRow = () => {
    setRows((prev) => [...prev, {
      payment_date: '', rate_pct: prev.at(-1)?.rate_pct ?? '', margin_pct: prev.at(-1)?.margin_pct ?? null,
      index_rate_pct: prev.at(-1)?.index_rate_pct ?? null, source: 'MANUAL',
    }])
    setDirty(true)
  }
  const isFloating = rows.some((r) => r.index_rate_pct != null && r.index_rate_pct !== '')
  const removeRow = (i: number) => { setRows((prev) => prev.filter((_, idx) => idx !== i)); setDirty(true) }

  return (
    <section>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-bold text-slate-800">
          <CalendarClock className="h-4 w-4 text-emerald-600" /> График купонных выплат
          <span className="text-xs font-normal text-slate-500">({rows.length})</span>
        </div>
        {canEdit && (
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-secondary h-8 px-2 text-xs" onClick={() => fromKase.mutate()} disabled={fromKase.isPending}
              title="Загрузить график с kase.kz (строки, исправленные вручную, сохраняются)">
              <CloudDownload className={`h-3.5 w-3.5 ${fromKase.isPending ? 'animate-pulse' : ''}`} /> С KASE
            </button>
            <button type="button" className="btn-secondary h-8 px-2 text-xs" onClick={() => generate.mutate()} disabled={generate.isPending}>
              <Wand2 className="h-3.5 w-3.5" /> По параметрам выпуска
            </button>
            <button type="button" className="btn-secondary h-8 px-2 text-xs" onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
              <Upload className="h-3.5 w-3.5" /> Импорт XLSX/CSV
            </button>
            <input ref={fileRef} type="file" accept=".xlsx,.xlsm,.csv" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = '' }} />
            <button type="button" className="btn-secondary h-8 px-2 text-xs" onClick={addRow}>
              <Plus className="h-3.5 w-3.5" /> Строка
            </button>
            <button type="button" className="btn-primary h-8 px-3 text-xs" onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
              <Save className="h-3.5 w-3.5" /> Сохранить
            </button>
          </div>
        )}
      </div>
      <p className="mb-2 text-xs leading-snug text-slate-600">
        «С KASE» загружает график и параметры выпуска с kase.kz; строки, исправленные или добавленные вручную, сохраняются.
        Импорт файла принимает ту же таблицу, скопированную в Excel. Если график заполнен, НКД, купоны и дюрация
        считаются по нему: по ставке каждого периода (плавающий купон — индекс + маржа) и фактическим датам выплат.
      </p>
      <div className="overflow-x-auto rounded-lg border border-slate-300">
        <table className="detail-table">
          <thead>
            <tr>
              <th>№</th><th>Дата выплаты</th><th>Ставка, % год.</th>{isFloating && <><th>Маржа, %</th><th>Индекс, %</th></>}<th>Сумма на 1 бумагу</th>
              <th>Фиксация реестра</th><th>Окончание выплаты</th><th>Источник</th>{canEdit && <th />}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="num text-slate-500">{r.seq ?? i + 1}</td>
                <td>{canEdit ? <input type="date" className="cell-input" value={r.payment_date ?? ''} onChange={(e) => update(i, 'payment_date', e.target.value)} /> : r.payment_date}</td>
                <td>{canEdit ? <input type="number" step="any" className="cell-input w-24 text-right tabular-nums" value={r.rate_pct ?? ''} onChange={(e) => update(i, 'rate_pct', e.target.value)} /> : r.rate_pct}</td>
                {isFloating && <>
                  <td>{canEdit ? <input type="number" step="any" className="cell-input w-20 text-right tabular-nums" value={r.margin_pct ?? ''} onChange={(e) => update(i, 'margin_pct', e.target.value)} /> : r.margin_pct ?? '—'}</td>
                  <td>{canEdit ? <input type="number" step="any" className="cell-input w-20 text-right tabular-nums" value={r.index_rate_pct ?? ''} onChange={(e) => update(i, 'index_rate_pct', e.target.value)} /> : r.index_rate_pct ?? '—'}</td>
                </>}
                <td>{canEdit ? <input type="number" step="any" className="cell-input w-28 text-right tabular-nums" value={r.amount_per_unit ?? ''} onChange={(e) => update(i, 'amount_per_unit', e.target.value)} /> : r.amount_per_unit ?? '—'}</td>
                <td>{canEdit ? <input type="date" className="cell-input" value={r.record_date ?? ''} onChange={(e) => update(i, 'record_date', e.target.value)} /> : r.record_date ?? '—'}</td>
                <td>{canEdit ? <input type="date" className="cell-input" value={r.payment_end_date ?? ''} onChange={(e) => update(i, 'payment_end_date', e.target.value)} /> : r.payment_end_date ?? '—'}</td>
                <td className={r.source === 'MANUAL' ? 'font-semibold text-amber-700' : 'text-slate-500'}>{SOURCE_LABEL[r.source ?? ''] ?? sourceLabel(r.source)}</td>
                {canEdit && <td><button type="button" className="text-slate-400 hover:text-red-600" onClick={() => removeRow(i)} title="Удалить"><Trash2 className="h-4 w-4" /></button></td>}
              </tr>
            ))}
            {!rows.length && (
              <tr><td colSpan={(canEdit ? 8 : 7) + (isFloating ? 2 : 0)} className="py-6 text-center text-slate-400">
                {q.isLoading ? 'Загрузка…' : 'График не заполнен — используется регулярный график по параметрам справочника'}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
