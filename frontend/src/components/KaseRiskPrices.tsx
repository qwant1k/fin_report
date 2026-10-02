import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Search, Upload } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { formatDate, formatNumber } from '@/lib/format'

type RiskPrice = {
  id: number
  trade_date: string
  valuation_date?: string | null
  instrument_code: string
  isin?: string | null
  algo?: string | null
  issuer_name?: string | null
  settlement_price?: number | null
  settlement_dirty_price?: number | null
  dohod?: number | null
  ytm?: number | null
  dtm?: number | null
  unit_ru?: string | null
  fetched_at: string
  source: string
}

function sourceLabel(source: string) {
  if (source === 'kase_gateway' || source === 'risk_parameters') return 'KASE (риск-параметры)'
  if (source.startsWith('file:')) return `Файл: ${source.slice(5)}`
  return source
}

/** «Расчетные цены_ФР» — prices calculated by KASE from risk parameters.
 *  Used for valuation when a bond has no market price on the date. */
export default function KaseRiskPrices({ reportDate }: { reportDate: string }) {
  const [query, setQuery] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const qc = useQueryClient()
  const can = useAuthStore((s) => s.can)

  const { data, isLoading } = useQuery<RiskPrice[]>({
    queryKey: ['kase-risk-prices', reportDate],
    queryFn: async () => (await api.get('/kase/risk/prices', { params: reportDate ? { report_date: reportDate } : undefined })).data,
  })

  const refresh = useMutation({
    mutationFn: async () => {
      if (!reportDate) throw new Error('Выберите дату')
      return (await api.post('/kase/risk/refresh', null, { params: { report_date: reportDate } })).data
    },
    onSuccess: (r) => {
      toast.success(`Цены по риск-параметрам: ${r.risk?.fetched ?? 0} строк`)
      qc.invalidateQueries({ queryKey: ['kase-risk-prices'] })
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail ?? err?.message ?? 'KASE не вернул файл риск-параметров'),
  })

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData()
      form.append('file', file)
      if (reportDate) form.append('report_date', reportDate)
      return (await api.post('/kase/risk/upload', form)).data
    },
    onSuccess: (r) => {
      toast.success(`Загружено ${r.risk?.fetched ?? 0} цен на ${formatDate(r.report_date)}`)
      qc.invalidateQueries({ queryKey: ['kase-risk-prices'] })
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail ?? 'Не удалось загрузить файл'),
  })

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (data ?? []).filter((r) => !needle || [r.instrument_code, r.isin, r.issuer_name, r.algo]
      .filter(Boolean).join(' ').toLowerCase().includes(needle))
  }, [data, query])

  return (
    <div className="space-y-4">
      <section className="card p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-800">Цены на основе риск-параметров («Расчетные цены_ФР»)</div>
            <p className="text-xs text-slate-500">
              Применяются к бумагам без рыночной цены на дату. Загружаются автоматически вместе с рыночными ценами,
              с сайта KASE по кнопке или из файла, скачанного с KASE (.xls / .xlsx).
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input className="input h-10 w-64 pl-9" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Код, ISIN, эмитент" />
            </label>
            {can('kase.refresh') && (
              <>
                <button className="btn-primary" disabled={!reportDate || refresh.isPending} onClick={() => refresh.mutate()}>
                  <RefreshCw className={`h-4 w-4 ${refresh.isPending ? 'animate-spin' : ''}`} /> Загрузить с KASE
                </button>
                <button className="btn-secondary" disabled={upload.isPending} onClick={() => fileRef.current?.click()}>
                  <Upload className="h-4 w-4" /> Из файла
                </button>
                <input
                  ref={fileRef} type="file" accept=".xls,.xlsx" className="hidden"
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = '' }}
                />
              </>
            )}
          </div>
        </div>
      </section>
      <div className="card overflow-hidden">
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>На дату</th>
                <th>Дата оценки</th>
                <th>Код</th>
                <th>ISIN</th>
                <th>Эмитент</th>
                <th>Алгоритм</th>
                <th className="text-right">Расчётная цена</th>
                <th className="text-right">Расчётная «грязная»</th>
                <th className="text-right">Доходность, %</th>
                <th className="text-right">Дней до погашения</th>
                <th>Единица</th>
                <th>Источник</th>
                <th>Загружено</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{formatDate(r.trade_date)}</td>
                  <td>{r.valuation_date ? formatDate(r.valuation_date) : '—'}</td>
                  <td className="font-medium">{r.instrument_code}</td>
                  <td>{r.isin ?? '—'}</td>
                  <td>{r.issuer_name ?? '—'}</td>
                  <td className="max-w-48 truncate" title={r.algo ?? ''}>{r.algo ?? '—'}</td>
                  <td className="text-right font-mono">{r.settlement_price != null ? formatNumber(r.settlement_price, 6) : '—'}</td>
                  <td className="text-right font-mono">{r.settlement_dirty_price != null ? formatNumber(r.settlement_dirty_price, 6) : '—'}</td>
                  <td className="text-right">{r.dohod != null ? formatNumber(r.dohod, 4) : '—'}</td>
                  <td className="text-right">{r.dtm != null ? formatNumber(r.dtm, 0) : '—'}</td>
                  <td>{r.unit_ru ?? '—'}</td>
                  <td>{sourceLabel(r.source)}</td>
                  <td>{formatDate(r.fetched_at)}</td>
                </tr>
              ))}
              {!rows.length && (
                <tr><td colSpan={13} className="py-8 text-center text-slate-400">
                  {isLoading ? 'Загрузка…' : 'Цен на основе риск-параметров за дату нет'}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
