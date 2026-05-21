import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Filter, RefreshCw, Search, X } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { KasePrice } from '@/lib/types'
import { formatDate, formatNumber } from '@/lib/format'

function todayIso() {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 10)
}

export default function KasePage() {
  const [reportDate, setReportDate] = useState(todayIso())
  const [query, setQuery] = useState('')
  const [securityType, setSecurityType] = useState('')
  const [unit, setUnit] = useState('')
  const [source, setSource] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [onlyDirtyPrice, setOnlyDirtyPrice] = useState(false)
  const [onlyMaturity, setOnlyMaturity] = useState(false)
  const qc = useQueryClient()

  const { data } = useQuery<KasePrice[]>({
    queryKey: ['kase-prices', reportDate],
    queryFn: async () => {
      const params = reportDate ? { report_date: reportDate } : undefined
      return (await api.get('/kase/prices', { params })).data
    },
  })

  const refresh = useMutation({
    mutationFn: async () => {
      if (!reportDate) throw new Error('Выберите дату для запроса KASE')
      return (await api.post('/kase/refresh', null, { params: { report_date: reportDate } })).data
    },
    onSuccess: (r) => {
      toast.success(`Получено: ${r.fetched}, новых записей: ${r.new_rows}`)
      qc.invalidateQueries({ queryKey: ['kase-prices'] })
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail ?? err?.message ?? 'Не удалось загрузить KASE')
    },
  })

  const reconcile = useMutation({
    mutationFn: async () => {
      if (!reportDate) throw new Error('Выберите дату для сверки')
      return (await api.post('/kase/reconcile', null, { params: { report_date: reportDate } })).data
    },
    onSuccess: (r) => toast.success(`Сверено цен: ${r.checked}`),
    onError: (err: any) => toast.error(err?.message ?? 'Не удалось выполнить сверку'),
  })

  const rows = data ?? []
  const securityTypes = useMemo(
    () => Array.from(new Set(rows.map((r) => r.fin_sec_ru ?? r.sec_type).filter((v): v is string => Boolean(v)))).sort(),
    [rows],
  )
  const units = useMemo(
    () => Array.from(new Set(rows.map((r) => r.unit_ru).filter((v): v is string => Boolean(v)))).sort(),
    [rows],
  )
  const sources = useMemo(
    () => Array.from(new Set(rows.map((r) => r.source).filter((v): v is string => Boolean(v)))).sort(),
    [rows],
  )

  const filteredRows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return rows.filter((r) => {
      const rowText = [
        r.instrument_code,
        r.isin,
        r.fin_sec_ru,
        r.sec_type,
        r.org_name_ru,
        r.instrument_name,
        r.unit_ru,
      ].filter(Boolean).join(' ').toLowerCase()
      if (needle && !rowText.includes(needle)) return false
      if (securityType && (r.fin_sec_ru ?? r.sec_type) !== securityType) return false
      if (unit && r.unit_ru !== unit) return false
      if (source && r.source !== source) return false
      if (dateFrom && r.trade_date < dateFrom) return false
      if (dateTo && r.trade_date > dateTo) return false
      if (onlyDirtyPrice && r.settlement_dirty_price == null) return false
      if (onlyMaturity && (r.dtm ?? r.duration) == null) return false
      return true
    })
  }, [dateFrom, dateTo, onlyDirtyPrice, onlyMaturity, query, rows, securityType, source, unit])

  const activeFilters = [
    query,
    securityType,
    unit,
    source,
    dateFrom,
    dateTo,
    onlyDirtyPrice,
    onlyMaturity,
  ].filter(Boolean).length

  const resetFilters = () => {
    setQuery('')
    setSecurityType('')
    setUnit('')
    setSource('')
    setDateFrom('')
    setDateTo('')
    setOnlyDirtyPrice(false)
    setOnlyMaturity(false)
  }

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-bold">KASE котировки</h1>
          <p className="text-sm text-slate-500">Рыночные цены KASE с сохранением колонок исходной таблицы</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <input
              type="date"
              className="input w-44 pr-9"
              value={reportDate}
              onChange={(e) => setReportDate(e.target.value)}
            />
            {reportDate && (
              <button
                type="button"
                onClick={() => setReportDate('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
                aria-label="Очистить дату"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
          <button onClick={() => refresh.mutate()} disabled={refresh.isPending || !reportDate} className="btn-primary">
            <RefreshCw className={`w-4 h-4 ${refresh.isPending ? 'animate-spin' : ''}`} /> Обновить с KASE
          </button>
          <button onClick={() => reconcile.mutate()} disabled={!reportDate} className="btn-secondary">
            <CheckCircle2 className="w-4 h-4" /> Сверить с портфелем
          </button>
        </div>
      </header>

      <section className="card p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Filter className="h-4 w-4 text-emerald-600" />
            Фильтры
            {activeFilters > 0 && (
              <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">
                {activeFilters}
              </span>
            )}
          </div>
          <div className="text-sm text-slate-500">
            Показано {formatNumber(filteredRows.length, 0)} из {formatNumber(rows.length, 0)}
          </div>
          {activeFilters > 0 && (
            <button type="button" onClick={resetFilters} className="btn-secondary h-8 px-2 text-xs">
              <X className="h-3.5 w-3.5" /> Сбросить
            </button>
          )}
        </div>

        <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          <label className="text-sm">
            <span className="label block">Поиск</span>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                className="input h-10 pl-9"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Код, ISIN, компания"
              />
            </div>
          </label>

          <label className="text-sm">
            <span className="label block">Вид бумаги</span>
            <select className="input h-10" value={securityType} onChange={(e) => setSecurityType(e.target.value)}>
              <option value="">Все виды</option>
              {securityTypes.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </label>

          <label className="text-sm">
            <span className="label block">Единица</span>
            <select className="input h-10" value={unit} onChange={(e) => setUnit(e.target.value)}>
              <option value="">Все единицы</option>
              {units.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </label>

          <label className="text-sm">
            <span className="label block">Источник</span>
            <select className="input h-10" value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">Все источники</option>
              {sources.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </label>

          <label className="text-sm">
            <span className="label block">На дату с</span>
            <input type="date" className="input h-10" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </label>

          <label className="text-sm">
            <span className="label block">На дату по</span>
            <input type="date" className="input h-10" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </label>

          <label className="flex h-10 items-center gap-2 self-end rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700">
            <input
              type="checkbox"
              checked={onlyDirtyPrice}
              onChange={(e) => setOnlyDirtyPrice(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
            />
            Есть грязная цена
          </label>

          <label className="flex h-10 items-center gap-2 self-end rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700">
            <input
              type="checkbox"
              checked={onlyMaturity}
              onChange={(e) => setOnlyMaturity(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
            />
            Есть срок
          </label>
        </div>
      </section>

      <div className="card overflow-hidden">
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>№</th>
                <th>Код</th>
                <th>ISIN</th>
                <th>Вид ценной бумаги</th>
                <th>Компания</th>
                <th>Рыночная цена</th>
                <th>Рыночная "грязная" цена</th>
                <th>Доходность до погашения, %</th>
                <th>Срок до погашения</th>
                <th>Единица измерения цены</th>
                <th>Источник</th>
                <th>Получено</th>
                <th>На дату</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((r, idx) => (
                <tr key={r.id}>
                  <td className="text-right">{idx + 1}</td>
                  <td className="font-medium">{r.instrument_code}</td>
                  <td>{r.isin ?? '—'}</td>
                  <td>{r.fin_sec_ru ?? r.sec_type ?? '—'}</td>
                  <td>{r.org_name_ru ?? r.instrument_name ?? '—'}</td>
                  <td className="text-right">{r.settlement_price != null || r.close_price != null ? formatNumber(r.settlement_price ?? r.close_price, 6) : '—'}</td>
                  <td className="text-right">{r.settlement_dirty_price != null ? formatNumber(r.settlement_dirty_price, 6) : '—'}</td>
                  <td className="text-right">{r.dohod != null || r.ytm != null ? formatNumber(r.dohod ?? ((r.ytm ?? 0) * 100), 2) : '—'}</td>
                  <td className="text-right">{r.dtm != null || r.duration != null ? formatNumber(r.dtm ?? r.duration, 0) : '—'}</td>
                  <td>{r.unit_ru ?? '—'}</td>
                  <td>{r.source}</td>
                  <td>{formatDate(r.fetched_at)}</td>
                  <td>{formatDate(r.trade_date)}</td>
                </tr>
              ))}
              {!filteredRows.length && (
                <tr>
                  <td colSpan={13} className="text-center text-slate-400 py-6">
                    Котировок нет
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
