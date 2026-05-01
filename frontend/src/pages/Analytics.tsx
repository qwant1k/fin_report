import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { TrendingUp, TrendingDown, Calendar, Filter } from 'lucide-react'

import { api } from '@/lib/api'
import { formatNumber, formatPct } from '@/lib/format'

interface CDUItem {
  id: number
  name: string
  short_name: string
  portfolio_type: 'PRIVATE_CDU' | 'NBRK_OWN' | 'NBRK_RESERVE'
  portfolio_code: string | null
  is_active: boolean
}

interface FundTrendRow {
  date: string
  market_value_total: number
  ytm_weighted: number | null
  duration_weighted: number | null
  cdu_count: number
}

interface PortfolioTrendRow {
  date: string
  cdu_id: number
  cdu_name: string
  cdu_short: string
  portfolio_type: string
  market_value_total: number
  ytm_weighted: number | null
  duration_weighted: number | null
}

interface BreakdownItem {
  category: string
  market_value: number
  pct: number
  count: number
}

interface PeriodSummary {
  from: string
  to: string
  data_points: number
  mv_start?: number
  mv_end?: number
  mv_delta?: number
  mv_delta_pct?: number
  best_day?: { date: string; delta: number; delta_pct: number } | null
  worst_day?: { date: string; delta: number; delta_pct: number } | null
  avg_ytm?: number | null
  avg_duration?: number | null
}

const COLORS = [
  '#1F6B38',
  '#70AD47',
  '#FFA000',
  '#1565C0',
  '#7E57C2',
  '#E53935',
  '#00ACC1',
  '#FF7043',
]

const CATEGORY_RU: Record<string, string> = {
  CASH: 'Cash',
  GOV_BONDS: 'ГЦБ МФ РК',
  AGENCY_BONDS: 'Агентские',
  MFO_BONDS: 'МФО',
  REVERSE_REPO: 'Обратное REPO',
  FOREIGN_BONDS: 'Ин. ЦБ (USD)',
  DEPOSIT: 'Депозиты',
  RECEIVABLES: 'Дебиторка',
  OTHER: 'Прочее',
}

const PORTFOLIO_TYPE_RU: Record<string, string> = {
  PRIVATE_CDU: 'Частные ДУ',
  NBRK_OWN: 'НБ РК Собст.',
  NBRK_RESERVE: 'НБ РК Спец.',
}

const PRESETS = [
  { label: '30 дней', days: 30 },
  { label: '90 дней', days: 90 },
  { label: '180 дней', days: 180 },
  { label: '365 дней', days: 365 },
]

export default function AnalyticsPage() {
  const today = new Date().toISOString().slice(0, 10)
  const [days, setDays] = useState(180)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [portfolioType, setPortfolioType] = useState<string>('')
  const [breakdownDate, setBreakdownDate] = useState(today)

  const periodParams = useMemo(() => {
    const p: Record<string, string | number> = {}
    if (from && to) {
      p.from = from
      p.to = to
    } else {
      p.days = days
    }
    if (portfolioType) p.portfolio_type = portfolioType
    return p
  }, [from, to, days, portfolioType])

  const cdus = useQuery<CDUItem[]>({
    queryKey: ['analytics-cdus'],
    queryFn: async () => (await api.get('/analytics/cdus')).data,
  })

  const fundTrend = useQuery<FundTrendRow[]>({
    queryKey: ['fund-trend', periodParams],
    queryFn: async () => (await api.get('/analytics/fund-trend', { params: periodParams })).data,
  })

  const portfolioTrend = useQuery<PortfolioTrendRow[]>({
    queryKey: ['portfolio-trend', periodParams],
    queryFn: async () =>
      (await api.get('/analytics/portfolio-trend', { params: periodParams })).data,
  })

  const breakdown = useQuery<{
    date: string
    total_market_value: number
    breakdown: BreakdownItem[]
  }>({
    queryKey: ['breakdown', breakdownDate],
    queryFn: async () =>
      (await api.get('/analytics/category-breakdown', { params: { date: breakdownDate } })).data,
  })

  const summary = useQuery<PeriodSummary>({
    queryKey: ['period-summary', periodParams],
    queryFn: async () =>
      (await api.get('/analytics/period-summary', { params: periodParams })).data,
  })

  // Pivot per-CDU trend → wide format for stacked area chart
  const pivotedTrend = useMemo(() => {
    const map = new Map<string, Record<string, number | string>>()
    const cduSet = new Set<string>()
    for (const r of portfolioTrend.data ?? []) {
      cduSet.add(r.cdu_short)
      const cur = map.get(r.date) ?? { date: r.date }
      cur[r.cdu_short] = r.market_value_total
      map.set(r.date, cur)
    }
    return {
      rows: Array.from(map.values()).sort((a, b) =>
        String(a.date).localeCompare(String(b.date)),
      ),
      cdus: Array.from(cduSet),
    }
  }, [portfolioTrend.data])

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Аналитика портфеля</h1>
          <p className="text-sm text-slate-500">
            Тренды на основе ежедневных снимков MV и Cash из импортированных Risk Report
          </p>
        </div>
      </header>

      {/* ───── Фильтры ───── */}
      <div className="card p-4 flex flex-wrap items-end gap-3">
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-slate-400" />
          <span className="text-sm text-slate-600 font-medium">Период:</span>
          {PRESETS.map((p) => (
            <button
              key={p.days}
              onClick={() => {
                setDays(p.days)
                setFrom('')
                setTo('')
              }}
              className={`btn ${
                days === p.days && !from
                  ? 'bg-kdif-green text-white'
                  : 'bg-white border border-slate-300 hover:bg-slate-50'
              } px-3 py-1 text-xs`}
            >
              {p.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <Calendar className="w-4 h-4 text-slate-400" />
          <input
            type="date"
            className="input w-36 py-1 text-sm"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
          <span className="text-slate-400">—</span>
          <input
            type="date"
            className="input w-36 py-1 text-sm"
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
        </div>

        <div className="flex items-center gap-2 ml-auto">
          <select
            className="input w-44 py-1 text-sm"
            value={portfolioType}
            onChange={(e) => setPortfolioType(e.target.value)}
          >
            <option value="">Все портфели</option>
            <option value="PRIVATE_CDU">Частные ДУ</option>
            <option value="NBRK_OWN">НБ РК — Собственные</option>
            <option value="NBRK_RESERVE">НБ РК — Спецрезерв</option>
          </select>
        </div>
      </div>

      {/* ───── Сводка за период ───── */}
      {summary.data && summary.data.data_points > 0 && (
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="card p-4">
            <div className="text-xs text-slate-500 uppercase">Начало периода</div>
            <div className="text-xl font-bold mt-1">
              {formatNumber(summary.data.mv_start ?? 0, 0)} ₸
            </div>
            <div className="text-xs text-slate-400 mt-1">{summary.data.from}</div>
          </div>
          <div className="card p-4">
            <div className="text-xs text-slate-500 uppercase">Конец периода</div>
            <div className="text-xl font-bold mt-1">
              {formatNumber(summary.data.mv_end ?? 0, 0)} ₸
            </div>
            <div className="text-xs text-slate-400 mt-1">{summary.data.to}</div>
          </div>
          <div className="card p-4">
            <div className="text-xs text-slate-500 uppercase">Изменение</div>
            <div
              className={`text-xl font-bold mt-1 flex items-center gap-1 ${
                (summary.data.mv_delta ?? 0) >= 0 ? 'text-emerald-700' : 'text-red-700'
              }`}
            >
              {(summary.data.mv_delta ?? 0) >= 0 ? (
                <TrendingUp className="w-5 h-5" />
              ) : (
                <TrendingDown className="w-5 h-5" />
              )}
              {formatNumber(summary.data.mv_delta ?? 0, 0)} ₸
            </div>
            <div className="text-xs text-slate-500 mt-1">
              {formatPct(summary.data.mv_delta_pct ?? 0)}
            </div>
          </div>
          <div className="card p-4">
            <div className="text-xs text-slate-500 uppercase">Средняя YTM / Duration</div>
            <div className="text-xl font-bold mt-1">
              {summary.data.avg_ytm != null ? formatPct(summary.data.avg_ytm) : '—'}
            </div>
            <div className="text-xs text-slate-500 mt-1">
              Duration:{' '}
              {summary.data.avg_duration != null
                ? formatNumber(summary.data.avg_duration, 2)
                : '—'}
            </div>
          </div>
        </section>
      )}

      {/* ───── Лучший / худший день ───── */}
      {summary.data?.best_day && summary.data.worst_day && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="card p-4 border-l-4 border-emerald-500">
            <div className="text-xs uppercase text-emerald-700">Лучший день</div>
            <div className="font-bold text-lg mt-1">
              {summary.data.best_day.date}: +{formatNumber(summary.data.best_day.delta, 0)} ₸
            </div>
            <div className="text-sm text-emerald-600">
              {formatPct(summary.data.best_day.delta_pct)}
            </div>
          </div>
          <div className="card p-4 border-l-4 border-red-500">
            <div className="text-xs uppercase text-red-700">Худший день</div>
            <div className="font-bold text-lg mt-1">
              {summary.data.worst_day.date}: {formatNumber(summary.data.worst_day.delta, 0)} ₸
            </div>
            <div className="text-sm text-red-600">
              {formatPct(summary.data.worst_day.delta_pct)}
            </div>
          </div>
        </div>
      )}

      {/* ───── Fund-level trend ───── */}
      <section className="card p-4">
        <h2 className="font-semibold mb-3">Активы Фонда — суммарная стоимость портфеля</h2>
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={fundTrend.data ?? []}>
              <defs>
                <linearGradient id="fundTotal" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#1F6B38" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="#1F6B38" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis
                tick={{ fontSize: 11 }}
                tickFormatter={(v) => (v / 1e9).toFixed(1) + ' млрд'}
              />
              <Tooltip
                formatter={(v: number) => v.toLocaleString('ru-RU', { maximumFractionDigits: 0 })}
              />
              <Area
                type="monotone"
                dataKey="market_value_total"
                name="MV Фонда"
                stroke="#1F6B38"
                fill="url(#fundTotal)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* ───── Per-CDU trend ───── */}
      <section className="card p-4">
        <h2 className="font-semibold mb-3">MV по ЧДУ / портфелям</h2>
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={pivotedTrend.rows}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis
                tick={{ fontSize: 11 }}
                tickFormatter={(v) => (v / 1e9).toFixed(1) + ' млрд'}
              />
              <Tooltip
                formatter={(v: number) => v.toLocaleString('ru-RU', { maximumFractionDigits: 0 })}
              />
              <Legend />
              {pivotedTrend.cdus.map((cdu, i) => (
                <Line
                  key={cdu}
                  type="monotone"
                  dataKey={cdu}
                  stroke={COLORS[i % COLORS.length]}
                  strokeWidth={2}
                  dot={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* ───── YTM/Duration trend ───── */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card p-4">
          <h2 className="font-semibold mb-3">YTM (взвеш.) — тренд</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={fundTrend.data ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v) => (v * 100).toFixed(1) + '%'}
                />
                <Tooltip formatter={(v: number) => formatPct(v)} />
                <Line
                  type="monotone"
                  dataKey="ytm_weighted"
                  stroke="#1565C0"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="card p-4">
          <h2 className="font-semibold mb-3">Duration — тренд</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={fundTrend.data ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v: number) => formatNumber(v, 2)} />
                <Line
                  type="monotone"
                  dataKey="duration_weighted"
                  stroke="#FFA000"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>

      {/* ───── Category breakdown ───── */}
      <section className="card p-4">
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <h2 className="font-semibold">Структура портфеля по категориям</h2>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">на дату:</span>
            <input
              type="date"
              className="input w-36 py-1 text-sm"
              value={breakdownDate}
              onChange={(e) => setBreakdownDate(e.target.value)}
            />
          </div>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={breakdown.data?.breakdown ?? []}
                  dataKey="market_value"
                  nameKey="category"
                  cx="50%"
                  cy="50%"
                  outerRadius={100}
                  label={(e) =>
                    `${CATEGORY_RU[e.category] ?? e.category} ${formatPct(e.pct)}`
                  }
                >
                  {(breakdown.data?.breakdown ?? []).map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(v: number) =>
                    v.toLocaleString('ru-RU', { maximumFractionDigits: 0 }) + ' ₸'
                  }
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={breakdown.data?.breakdown ?? []} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis
                  type="number"
                  tickFormatter={(v) => (v / 1e9).toFixed(1) + ' млрд'}
                  tick={{ fontSize: 11 }}
                />
                <YAxis
                  type="category"
                  dataKey="category"
                  tick={{ fontSize: 11 }}
                  width={120}
                  tickFormatter={(v) => CATEGORY_RU[v] ?? v}
                />
                <Tooltip
                  formatter={(v: number) =>
                    v.toLocaleString('ru-RU', { maximumFractionDigits: 0 }) + ' ₸'
                  }
                />
                <Bar dataKey="market_value" fill="#1F6B38" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>

      {/* ───── CDU list (для фильтра) ───── */}
      <section className="card p-4">
        <h2 className="font-semibold mb-3">Зарегистрированные ЧДУ и портфели</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {(cdus.data ?? []).map((c) => (
            <div key={c.id} className="border border-slate-200 rounded-md p-3">
              <div className="font-medium">{c.short_name}</div>
              <div className="text-xs text-slate-500">{c.name}</div>
              <div className="text-xs text-slate-400 mt-1">
                {PORTFOLIO_TYPE_RU[c.portfolio_type] ?? c.portfolio_type}
                {c.portfolio_code ? ` • код: ${c.portfolio_code}` : ''}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
