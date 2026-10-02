import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  CalendarDays,
  Filter,
  ListChecks,
  RefreshCw,
  Search,
  SlidersHorizontal,
} from 'lucide-react'

import { api } from '@/lib/api'
import { formatDate, formatNumber } from '@/lib/format'
import { CDU } from '@/lib/types'
import { EmptyState, PageHeader, StatCard } from '@/components/ui'

interface OperationRow {
  id: number
  cdu_id: number
  cdu_name: string | null
  cdu_short: string | null
  trade_date: string | null
  value_date: string | null
  operation_type: string
  direction: string | null
  instrument_category: string | null
  instrument_code: string | null
  isin: string | null
  description: string | null
  deal_id: string | null
  amount_kzt: number
  amount_ccy: number | null
  currency: string
  quantity: number | null
  face_value: number | null
  market_price: number | null
  price_original: number | null
  price_kase: number | null
  price_final: number | null
  price_flag: boolean
  price_diff_pct: number | null
  ytm: number | null
  repo_rate_pct: number | null
  repo_term_days: number | null
  commission_total: number | null
  source_doc_id: number | null
  source_file: string | null
  source_row_idx: number | null
  is_manual: boolean
  is_synthetic: boolean
  is_active: boolean
  created_by: string | null
  created_at: string | null
}

interface OperationSummaryItem {
  operation_type: string
  count: number
  amount_kzt: number
}

interface OperationsResponse {
  from: string
  to: string
  rows_total: number
  rows: OperationRow[]
  summary: {
    by_operation: OperationSummaryItem[]
    flagged_prices: number
    net_amount_kzt: number
  }
}

const OP_LABEL: Record<string, string> = {
  BUY: 'Покупка',
  SELL: 'Продажа',
  REPO: 'REPO',
  REPO_OPEN: 'Открытие REPO',
  REPO_CLOSE: 'Закрытие REPO',
  COUPON: 'Купон',
  REDEMPTION: 'Погашение',
  DEPOSIT_OPEN: 'Депозит',
  DEPOSIT_CLOSE: 'Закрытие депозита',
  FX_BUY: 'FX покупка',
  FX_SELL: 'FX продажа',
  CASH_TOPUP: 'Пополнение',
  CASH_WITHDRAW: 'Вывод ДС',
  OTHER: 'Прочее',
}

const OP_COLOR: Record<string, string> = {
  BUY: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  SELL: 'bg-red-50 text-red-700 ring-red-600/20',
  REPO_OPEN: 'bg-amber-50 text-amber-700 ring-amber-600/20',
  REPO_CLOSE: 'bg-blue-50 text-blue-700 ring-blue-600/20',
  COUPON: 'bg-cyan-50 text-cyan-700 ring-cyan-600/20',
  REDEMPTION: 'bg-violet-50 text-violet-700 ring-violet-600/20',
}

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function minusDays(days: number) {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

function money(value: number | null | undefined) {
  if (value == null) return '—'
  return `${formatNumber(value, 0)} ₸`
}

export default function OperationsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialDate = searchParams.get('date')
  const [from, setFrom] = useState(initialDate ?? minusDays(30))
  const [to, setTo] = useState(initialDate ?? todayIso())
  const [cduId, setCduId] = useState(searchParams.get('cdu_id') ?? '')
  const [operationType, setOperationType] = useState('')
  const [query, setQuery] = useState('')
  const [drilldown, setDrilldown] = useState<string | null>(null)

  useEffect(() => {
    const next = new URLSearchParams()
    if (from === to) next.set('date', to)
    if (cduId) next.set('cdu_id', cduId)
    setSearchParams(next, { replace: true })
  }, [cduId, from, setSearchParams, to])

  const cdus = useQuery<CDU[]>({
    queryKey: ['cdus'],
    queryFn: async () => (await api.get('/settings/cdus')).data,
  })

  const params = useMemo(() => ({
    from,
    to,
    cdu_id: cduId || undefined,
    operation_type: operationType || undefined,
    q: query || undefined,
    limit: 500,
  }), [cduId, from, operationType, query, to])

  const operations = useQuery<OperationsResponse>({
    queryKey: ['operations', params],
    queryFn: async () => (await api.get('/operations', { params })).data,
  })

  const rows = operations.data?.rows ?? []
  const byOperation = operations.data?.summary.by_operation ?? []
  const totalBuys = byOperation.find((x) => x.operation_type === 'BUY')?.count ?? 0
  const totalSells = byOperation.find((x) => x.operation_type === 'SELL')?.count ?? 0
  const totalRepo = byOperation
    .filter((x) => x.operation_type.startsWith('REPO'))
    .reduce((sum, x) => sum + x.count, 0)
  const applyQuickFilter = (type: string, label: string) => {
    setOperationType(type)
    setDrilldown(label)
  }
  const resetQuickFilter = () => {
    setOperationType('')
    setDrilldown(null)
  }

  return (
    <div className="space-y-6">
      <PageHeader
        icon={ListChecks}
        title="Операции"
        subtitle="Единый журнал сделок, движений и источников из Trade ledger"
        actions={
          <button className="btn-secondary" onClick={() => operations.refetch()}>
            <RefreshCw className={`h-4 w-4 ${operations.isFetching ? 'animate-spin' : ''}`} />
            Обновить
          </button>
        }
      />

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="Всего строк"
          value={operations.data?.rows_total ?? 0}
          format={(n) => formatNumber(n, 0)}
          subtitle={`Показано ${formatNumber(rows.length, 0)}`}
          icon={ListChecks}
          accent="emerald"
          active={drilldown === 'all'}
          onClick={() => applyQuickFilter('', 'all')}
        />
        <StatCard
          title="Покупки"
          value={totalBuys}
          format={(n) => formatNumber(n, 0)}
          icon={Filter}
          accent="teal"
          active={operationType === 'BUY'}
          onClick={() => applyQuickFilter('BUY', 'BUY')}
        />
        <StatCard
          title="Продажи"
          value={totalSells}
          format={(n) => formatNumber(n, 0)}
          icon={Filter}
          accent="red"
          active={operationType === 'SELL'}
          onClick={() => applyQuickFilter('SELL', 'SELL')}
        />
        <StatCard
          title="REPO"
          value={totalRepo}
          format={(n) => formatNumber(n, 0)}
          subtitle={(operations.data?.summary.flagged_prices ?? 0) > 0 ? `${operations.data?.summary.flagged_prices} KASE-флагов` : 'Без ценовых флагов'}
          icon={SlidersHorizontal}
          accent={(operations.data?.summary.flagged_prices ?? 0) > 0 ? 'amber' : 'sky'}
          active={operationType === 'REPO'}
          onClick={() => applyQuickFilter('REPO', 'REPO')}
        />
      </section>

      {drilldown && (
        <section className="card flex flex-wrap items-center justify-between gap-3 p-4">
          <div>
            <h2 className="section-title">
              {drilldown === 'all' ? 'Все операции за выбранный период' : `Отбор: ${OP_LABEL[operationType] ?? drilldown}`}
            </h2>
            <p className="text-sm text-slate-500">
              Период: {formatDate(from)} - {formatDate(to)} · строк: {formatNumber(operations.data?.rows_total ?? 0, 0)}
            </p>
          </div>
          <button type="button" onClick={resetQuickFilter} className="btn-secondary">
            <ArrowLeft className="h-4 w-4" />
            Назад
          </button>
        </section>
      )}

      <section className="card p-4">
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[160px_160px_220px_200px_1fr]">
          <label>
            <span className="label">С даты</span>
            <div className="relative">
              <CalendarDays className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input type="date" className="input pl-9" value={from} onChange={(e) => setFrom(e.target.value)} />
            </div>
          </label>
          <label>
            <span className="label">По дату</span>
            <div className="relative">
              <CalendarDays className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input type="date" className="input pl-9" value={to} onChange={(e) => setTo(e.target.value)} />
            </div>
          </label>
          <label>
            <span className="label">ЧДУ</span>
            <select className="input" value={cduId} onChange={(e) => setCduId(e.target.value)}>
              <option value="">Все ЧДУ</option>
              {cdus.data?.map((cdu) => (
                <option key={cdu.id} value={cdu.id}>{cdu.short_name}</option>
              ))}
            </select>
          </label>
          <label>
            <span className="label">Тип операции</span>
            <select
              className="input"
              value={operationType}
              onChange={(e) => {
                setOperationType(e.target.value)
                setDrilldown(null)
              }}
            >
              <option value="">Все типы</option>
              {Object.entries(OP_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <label>
            <span className="label">Поиск</span>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                className="input pl-9"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="ISIN, тикер, сделка, описание"
              />
            </div>
          </label>
        </div>
      </section>

      <section className="card overflow-hidden">
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>Дата</th>
                <th>ЧДУ</th>
                <th>Операция</th>
                <th>Инструмент</th>
                <th>Кол-во / номинал</th>
                <th>Цена</th>
                <th>Сумма</th>
                <th>Источник</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <div className="font-medium">{formatDate(row.trade_date)}</div>
                    <div className="text-xs text-slate-500">расч. {formatDate(row.value_date)}</div>
                  </td>
                  <td>
                    <div className="font-semibold">{row.cdu_short ?? row.cdu_name ?? '—'}</div>
                    <div className="text-xs text-slate-500">#{row.id}</div>
                  </td>
                  <td>
                    <span className={`badge ${OP_COLOR[row.operation_type] ?? 'bg-slate-100 text-slate-700 ring-slate-500/20'}`}>
                      {OP_LABEL[row.operation_type] ?? row.operation_type}
                    </span>
                    {row.price_flag && (
                      <div className="mt-1 text-xs text-amber-700">цена заменена на KASE</div>
                    )}
                  </td>
                  <td>
                    <div className="font-medium">{row.instrument_code ?? row.isin ?? '—'}</div>
                    <div className="text-xs text-slate-500">{row.instrument_category ?? row.description ?? '—'}</div>
                    {row.deal_id && <div className="text-xs text-slate-400">сделка {row.deal_id}</div>}
                  </td>
                  <td className="text-right">
                    <div>{formatNumber(row.quantity ?? row.face_value, 2)}</div>
                    {row.face_value != null && <div className="text-xs text-slate-500">ном. {formatNumber(row.face_value, 0)}</div>}
                  </td>
                  <td className="text-right">
                    <div>{formatNumber(row.price_final ?? row.market_price, 4)}</div>
                    {row.price_kase != null && <div className="text-xs text-slate-500">KASE {formatNumber(row.price_kase, 4)}</div>}
                  </td>
                  <td className={`text-right font-semibold ${row.amount_kzt < 0 ? 'text-red-600' : 'text-emerald-700'}`}>
                    {money(row.amount_kzt)}
                  </td>
                  <td>
                    <div className="max-w-[260px] truncate text-xs text-slate-600" title={row.source_file ?? ''}>
                      {row.source_file ?? (row.is_manual ? 'ручная операция' : '—')}
                    </div>
                    <div className="text-xs text-slate-400">
                      {row.source_row_idx ? `строка ${row.source_row_idx}` : row.created_by ?? ''}
                    </div>
                  </td>
                </tr>
              ))}
              {!rows.length && (
                <tr>
                  <td colSpan={8} className="py-10">
                    <EmptyState
                      icon={ListChecks}
                      title="Операций не найдено"
                      description="Измените фильтры или загрузите TradeReport за выбранный период."
                      className="border-0 bg-transparent py-6"
                    />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
