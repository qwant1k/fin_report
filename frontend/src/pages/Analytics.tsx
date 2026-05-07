import { type ReactNode, useEffect, useMemo, useState } from 'react'
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
import {
  BarChart3,
  Calendar,
  Database,
  Filter,
  Layers,
  LineChart as LineChartIcon,
  PieChart as PieChartIcon,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Table2,
  type LucideIcon,
} from 'lucide-react'
import clsx from 'clsx'

import { api } from '@/lib/api'
import { formatDate, formatNumber, formatPct } from '@/lib/format'

type ChartType = 'line' | 'area' | 'bar' | 'pie' | 'table'

interface AnalyticsMeta {
  min_date: string | null
  max_date: string | null
  sources: Option[]
  metrics: Option[]
  group_by: Option[]
  categories: Option[]
  cdus: CDUItem[]
}

interface Option {
  value: string
  label: string
}

interface CDUItem {
  id: number
  name: string
  short_name: string
  portfolio_type: string
  portfolio_code: string | null
  is_active: boolean
}

interface WorkbenchRow {
  date: string | null
  cdu_id: number | null
  cdu_name: string | null
  cdu_short: string | null
  portfolio_type: string | null
  category: string | null
  instrument: string | null
  metric_value: number | null
  market_value: number
  daily_change: number
  ytm: number | null
  duration: number | null
  count: number
}

interface WorkbenchResponse {
  source: string
  metric: string
  group_by: string[]
  from: string
  to: string
  rows_total: number
  rows: WorkbenchRow[]
}

const COLORS = ['#059669', '#0284C7', '#F59E0B', '#DB2777', '#7C3AED', '#0891B2', '#EA580C', '#475569']

const PORTFOLIO_TYPE_RU: Record<string, string> = {
  PRIVATE_CDU: 'Частные ДУ',
  NBRK_OWN: 'НБ РК собственные',
  NBRK_RESERVE: 'НБ РК спецрезерв',
}

const PRESETS = [
  { label: '30 дней', days: 30 },
  { label: '90 дней', days: 90 },
  { label: '180 дней', days: 180 },
  { label: '365 дней', days: 365 },
  { label: 'Все', days: null },
]

const QUICK_VIEWS = [
  { label: 'Динамика фонда', source: 'summary', metric: 'market_value', groupBy: ['date'], chart: 'area' as ChartType },
  { label: 'ЧДУ по датам', source: 'summary', metric: 'market_value', groupBy: ['date', 'cdu'], chart: 'line' as ChartType },
  { label: 'Структура', source: 'positions', metric: 'market_value', groupBy: ['category'], chart: 'pie' as ChartType },
  { label: 'Категории ЧДУ', source: 'positions', metric: 'market_value', groupBy: ['cdu', 'category'], chart: 'bar' as ChartType },
  { label: 'Доходность', source: 'summary', metric: 'ytm', groupBy: ['date', 'cdu'], chart: 'line' as ChartType },
  { label: 'Дюрация', source: 'summary', metric: 'duration', groupBy: ['date', 'cdu'], chart: 'line' as ChartType },
  { label: 'Инструменты', source: 'lots', metric: 'market_value', groupBy: ['category', 'instrument'], chart: 'bar' as ChartType },
]

const CHART_OPTIONS: { type: ChartType; label: string; icon: LucideIcon }[] = [
  { type: 'line', label: 'Линия', icon: LineChartIcon },
  { type: 'area', label: 'Область', icon: LineChartIcon },
  { type: 'bar', label: 'Столбцы', icon: BarChart3 },
  { type: 'pie', label: 'Доли', icon: PieChartIcon },
  { type: 'table', label: 'Таблица', icon: Table2 },
]

function minusDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00`)
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

function toggleList<T>(items: T[], value: T): T[] {
  return items.includes(value) ? items.filter((x) => x !== value) : [...items, value]
}

function valueLabel(row: WorkbenchRow): string {
  return row.instrument || row.category || row.cdu_short || row.date || 'Итого'
}

function seriesLabel(row: WorkbenchRow, groupBy: string[]): string {
  if (groupBy.includes('instrument')) return row.instrument || 'Инструмент'
  if (groupBy.includes('category') && groupBy.includes('cdu')) return `${row.cdu_short ?? ''} ${row.category ?? ''}`.trim()
  if (groupBy.includes('category')) return row.category || 'Категория'
  if (groupBy.includes('cdu')) return row.cdu_short || row.cdu_name || 'ЧДУ'
  if (groupBy.includes('portfolio_type')) return row.portfolio_type ? PORTFOLIO_TYPE_RU[row.portfolio_type] ?? row.portfolio_type : 'Тип'
  return 'Значение'
}

function formatMetric(metric: string, value: number | null | undefined): string {
  if (metric === 'ytm' || metric === 'pct' || metric === 'return_pct') return formatPct(value)
  if (metric === 'duration') return formatNumber(value, 2)
  if (metric === 'count') return formatNumber(value, 0)
  return `${formatNumber(value, 0)} ₸`
}

function sameGroups(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((x, index) => x === b[index])
}

export default function AnalyticsPage() {
  const meta = useQuery<AnalyticsMeta>({
    queryKey: ['analytics-meta'],
    queryFn: async () => (await api.get('/analytics/meta')).data,
  })

  const [source, setSource] = useState('positions')
  const [metric, setMetric] = useState('market_value')
  const [groupBy, setGroupBy] = useState<string[]>(['date', 'cdu', 'category'])
  const [chartType, setChartType] = useState<ChartType>('bar')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [portfolioType, setPortfolioType] = useState('')
  const [selectedCdus, setSelectedCdus] = useState<number[]>([])
  const [selectedCategories, setSelectedCategories] = useState<string[]>([])
  const [minValue, setMinValue] = useState('')
  const [maxValue, setMaxValue] = useState('')
  const [limit, setLimit] = useState(500)
  const [sort, setSort] = useState('date_asc')

  useEffect(() => {
    if (!meta.data?.max_date || to) return
    setTo(meta.data.max_date)
    setFrom(minusDays(meta.data.max_date, 180))
  }, [meta.data?.max_date, to])

  const params = useMemo(
    () => ({
      source,
      metric,
      group_by: groupBy.join(','),
      from,
      to,
      portfolio_type: portfolioType || undefined,
      cdu_ids: selectedCdus.join(',') || undefined,
      categories: selectedCategories.join(',') || undefined,
      min_value: minValue || undefined,
      max_value: maxValue || undefined,
      limit,
      sort,
    }),
    [source, metric, groupBy, from, to, portfolioType, selectedCdus, selectedCategories, minValue, maxValue, limit, sort],
  )

  const workbench = useQuery<WorkbenchResponse>({
    queryKey: ['analytics-workbench', params],
    enabled: Boolean(from && to),
    queryFn: async () => (await api.get('/analytics/workbench', { params })).data,
  })

  const rows = workbench.data?.rows ?? []

  const chartData = useMemo(() => {
    if (!groupBy.includes('date')) {
      return rows.map((row) => ({
        name: valueLabel(row),
        value: row.metric_value ?? 0,
        metric_value: row.metric_value ?? 0,
      }))
    }

    const byDate = new Map<string, Record<string, string | number>>()
    for (const row of rows) {
      const dateKey = row.date ?? ''
      const name = seriesLabel(row, groupBy)
      const current = byDate.get(dateKey) ?? { date: dateKey }
      current[name] = row.metric_value ?? 0
      byDate.set(dateKey, current)
    }
    return Array.from(byDate.values()).sort((a, b) => String(a.date).localeCompare(String(b.date)))
  }, [rows, groupBy])

  const series = useMemo(() => {
    if (!groupBy.includes('date')) return ['metric_value']
    const s = new Set<string>()
    for (const row of rows) s.add(seriesLabel(row, groupBy))
    return Array.from(s)
  }, [rows, groupBy])

  const totals = useMemo(() => {
    const total = rows.reduce((sum, row) => sum + (row.market_value || 0), 0)
    const metricTotal = rows.reduce((sum, row) => sum + (row.metric_value || 0), 0)
    const count = rows.reduce((sum, row) => sum + (row.count || 0), 0)
    const ytmWeight = rows.reduce((sum, row) => sum + (row.ytm != null ? Math.abs(row.market_value || 0) : 0), 0)
    const ytm = ytmWeight
      ? rows.reduce((sum, row) => sum + (row.ytm != null ? row.ytm * Math.abs(row.market_value || 0) : 0), 0) / ytmWeight
      : null
    const durWeight = rows.reduce((sum, row) => sum + (row.duration != null ? Math.abs(row.market_value || 0) : 0), 0)
    const duration = durWeight
      ? rows.reduce((sum, row) => sum + (row.duration != null ? row.duration * Math.abs(row.market_value || 0) : 0), 0) / durWeight
      : null
    return { total, metricTotal, count, ytm, duration }
  }, [rows])

  const cduTypeById = useMemo(() => {
    const map = new Map<number, string>()
    for (const cdu of meta.data?.cdus ?? []) map.set(cdu.id, cdu.portfolio_type)
    return map
  }, [meta.data?.cdus])

  const activeFilters = selectedCdus.length + selectedCategories.length + (portfolioType ? 1 : 0) + (minValue ? 1 : 0) + (maxValue ? 1 : 0)

  const applyPreset = (days: number | null) => {
    const maxDate = meta.data?.max_date
    const minDate = meta.data?.min_date
    if (!maxDate) return
    setTo(maxDate)
    setFrom(days == null ? (minDate ?? maxDate) : minusDays(maxDate, days))
  }

  const applyQuickView = (view: (typeof QUICK_VIEWS)[number]) => {
    setSource(view.source)
    setMetric(view.metric)
    setGroupBy(view.groupBy)
    setChartType(view.chart)
    if (view.source !== 'positions') setSelectedCategories([])
  }

  const yAxisFormatter = (value: number) => (
    metric === 'market_value' ? `${(Number(value) / 1e9).toFixed(1)} млрд` : formatMetric(metric, Number(value))
  )

  const chart = (
    <ResponsiveContainer width="100%" height="100%">
      {chartType === 'area' ? (
        <AreaChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey={groupBy.includes('date') ? 'date' : 'name'} tick={{ fontSize: 11, fill: '#64748b' }} />
          <YAxis tick={{ fontSize: 11, fill: '#64748b' }} tickFormatter={yAxisFormatter} />
          <Tooltip formatter={(v: number) => formatMetric(metric, v)} />
          <Legend />
          {series.map((s, i) => (
            <Area key={s} type="monotone" dataKey={s} stroke={COLORS[i % COLORS.length]} fill={COLORS[i % COLORS.length]} fillOpacity={0.18} strokeWidth={2.5} />
          ))}
        </AreaChart>
      ) : chartType === 'line' ? (
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey={groupBy.includes('date') ? 'date' : 'name'} tick={{ fontSize: 11, fill: '#64748b' }} />
          <YAxis tick={{ fontSize: 11, fill: '#64748b' }} tickFormatter={yAxisFormatter} />
          <Tooltip formatter={(v: number) => formatMetric(metric, v)} />
          <Legend />
          {series.map((s, i) => (
            <Line key={s} type="monotone" dataKey={s} stroke={COLORS[i % COLORS.length]} strokeWidth={2.5} dot={false} />
          ))}
        </LineChart>
      ) : chartType === 'pie' ? (
        <PieChart>
          <Pie data={chartData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={126} innerRadius={56} paddingAngle={2} label={(entry) => entry.name}>
            {chartData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Pie>
          <Tooltip formatter={(v: number) => formatMetric(metric, v)} />
        </PieChart>
      ) : (
        <BarChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey={groupBy.includes('date') ? 'date' : 'name'} tick={{ fontSize: 11, fill: '#64748b' }} />
          <YAxis tick={{ fontSize: 11, fill: '#64748b' }} tickFormatter={yAxisFormatter} />
          <Tooltip formatter={(v: number) => formatMetric(metric, v)} />
          <Legend />
          {(groupBy.includes('date') ? series : ['metric_value']).map((s, i) => (
            <Bar key={s} dataKey={s} fill={COLORS[i % COLORS.length]} radius={[4, 4, 0, 0]} />
          ))}
        </BarChart>
      )}
    </ResponsiveContainer>
  )

  return (
    <div className="space-y-5">
      <header className="overflow-hidden rounded-lg border border-slate-800 bg-slate-950 text-white shadow-card">
        <div className="flex flex-wrap items-start justify-between gap-4 p-5">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1 text-xs font-semibold text-emerald-200">
              <Database className="h-3.5 w-3.5" />
              {meta.data?.min_date ? formatDate(meta.data.min_date) : '—'} - {meta.data?.max_date ? formatDate(meta.data.max_date) : '—'}
            </div>
            <h1 className="text-3xl font-black tracking-normal">Аналитика</h1>
            <div className="mt-1 max-w-3xl text-sm font-medium text-slate-300">
              Графики, структура, инструменты, доходность и дюрация по всем загруженным данным.
            </div>
          </div>
          <button type="button" onClick={() => workbench.refetch()} className="btn border border-white/10 bg-white text-slate-950 hover:bg-emerald-50">
            <RefreshCw className={clsx('h-4 w-4', workbench.isFetching && 'animate-spin')} />
            Обновить
          </button>
        </div>
        <div className="grid grid-cols-2 border-t border-white/10 md:grid-cols-4">
          <HeaderStat label="Источник" value={meta.data?.sources.find((x) => x.value === source)?.label ?? source} />
          <HeaderStat label="Метрика" value={meta.data?.metrics.find((x) => x.value === metric)?.label ?? metric} />
          <HeaderStat label="Группировка" value={groupBy.length ? groupBy.join(', ') : 'нет'} />
          <HeaderStat label="Фильтры" value={formatNumber(activeFilters, 0)} />
        </div>
      </header>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(340px,430px)_1fr]">
        <aside className="soft-panel xl:sticky xl:top-6 xl:self-start">
          <div className="border-b border-slate-200 p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 font-bold text-slate-950">
                <Filter className="h-4 w-4 text-emerald-600" />
                Фильтр
              </div>
              <div className="rounded-full bg-cyan-100 px-2.5 py-1 text-xs font-bold text-cyan-800">
                {formatNumber(rows.length, 0)} строк
              </div>
            </div>
          </div>

          <div className="space-y-5 p-4">
            <FilterBlock icon={Database} title="Данные">
              <div className="grid grid-cols-2 gap-2">
                <label className="text-sm">
                  <span className="label block">Источник</span>
                  <select className="input h-10" value={source} onChange={(e) => setSource(e.target.value)}>
                    {meta.data?.sources.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
                  </select>
                </label>
                <label className="text-sm">
                  <span className="label block">Метрика</span>
                  <select className="input h-10" value={metric} onChange={(e) => setMetric(e.target.value)}>
                    {meta.data?.metrics.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
                  </select>
                </label>
              </div>
            </FilterBlock>

            <FilterBlock icon={Calendar} title="Период">
              <div className="grid grid-cols-2 gap-2">
                <label className="text-sm">
                  <span className="label block">С даты</span>
                  <input type="date" className="input h-10" value={from} onChange={(e) => setFrom(e.target.value)} />
                </label>
                <label className="text-sm">
                  <span className="label block">По дату</span>
                  <input type="date" className="input h-10" value={to} onChange={(e) => setTo(e.target.value)} />
                </label>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {PRESETS.map((preset) => (
                  <button key={preset.label} type="button" onClick={() => applyPreset(preset.days)} className="control-chip px-2.5 py-1 text-xs">
                    {preset.label}
                  </button>
                ))}
              </div>
            </FilterBlock>

            <FilterBlock icon={Layers} title="Срезы">
              <label className="block text-sm">
                <span className="label block">Тип портфеля</span>
                <select className="input h-10" value={portfolioType} onChange={(e) => setPortfolioType(e.target.value)}>
                  <option value="">Все</option>
                  <option value="PRIVATE_CDU">Частные ДУ</option>
                  <option value="NBRK_OWN">НБ РК собственные</option>
                  <option value="NBRK_RESERVE">НБ РК спецрезерв</option>
                </select>
              </label>

              <div className="mt-3">
                <div className="label">Группировка</div>
                <div className="grid grid-cols-2 gap-2">
                  {meta.data?.group_by.map((item) => (
                    <CheckboxPill
                      key={item.value}
                      checked={groupBy.includes(item.value)}
                      label={item.label}
                      onChange={() => setGroupBy(toggleList(groupBy, item.value))}
                    />
                  ))}
                </div>
              </div>
            </FilterBlock>

            <FilterBlock icon={Search} title="Выборки">
              <MultiSelectList title="ЧДУ">
                {meta.data?.cdus.map((cdu) => (
                  <CheckboxRow
                    key={cdu.id}
                    checked={selectedCdus.includes(cdu.id)}
                    label={cdu.short_name}
                    onChange={() => setSelectedCdus(toggleList(selectedCdus, cdu.id))}
                  />
                ))}
              </MultiSelectList>

              <div className="mt-3">
                <MultiSelectList title="Категории">
                  {meta.data?.categories.map((cat) => (
                    <CheckboxRow
                      key={cat.value}
                      checked={selectedCategories.includes(cat.value)}
                      label={cat.label}
                      onChange={() => setSelectedCategories(toggleList(selectedCategories, cat.value))}
                    />
                  ))}
                </MultiSelectList>
              </div>
            </FilterBlock>

            <FilterBlock icon={SlidersHorizontal} title="Ограничения">
              <div className="grid grid-cols-2 gap-2">
                <label className="text-sm">
                  <span className="label block">Мин.</span>
                  <input className="input h-10" value={minValue} onChange={(e) => setMinValue(e.target.value)} />
                </label>
                <label className="text-sm">
                  <span className="label block">Макс.</span>
                  <input className="input h-10" value={maxValue} onChange={(e) => setMaxValue(e.target.value)} />
                </label>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <label className="text-sm">
                  <span className="label block">Сортировка</span>
                  <select className="input h-10" value={sort} onChange={(e) => setSort(e.target.value)}>
                    <option value="date_asc">Дата ↑</option>
                    <option value="date_desc">Дата ↓</option>
                    <option value="value_desc">Значение ↓</option>
                    <option value="value_asc">Значение ↑</option>
                  </select>
                </label>
                <label className="text-sm">
                  <span className="label block">Лимит</span>
                  <input type="number" min={1} max={5000} className="input h-10" value={limit} onChange={(e) => setLimit(Number(e.target.value) || 500)} />
                </label>
              </div>
            </FilterBlock>
          </div>
        </aside>

        <main className="space-y-4">
          <section className="soft-panel p-3">
            <div className="flex flex-wrap gap-2">
              {QUICK_VIEWS.map((view) => {
                const active = source === view.source && metric === view.metric && chartType === view.chart && sameGroups(groupBy, view.groupBy)
                return (
                  <button
                    key={view.label}
                    type="button"
                    onClick={() => applyQuickView(view)}
                    className={clsx('control-chip', active && 'control-chip-active')}
                  >
                    {view.label}
                  </button>
                )
              })}
            </div>
          </section>

          <section className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-4">
            <StatCard accent="bg-cyan-500" label="Строк" value={formatNumber(workbench.data?.rows_total ?? 0, 0)} subvalue={`Показано ${formatNumber(rows.length, 0)}`} />
            <StatCard accent="bg-emerald-500" label="Market value" value={`${formatNumber(totals.total, 0)} ₸`} subvalue={formatMetric(metric, totals.metricTotal)} />
            <StatCard accent="bg-amber-500" label="YTM" value={formatPct(totals.ytm)} subvalue={`Инструментов: ${formatNumber(totals.count, 0)}`} />
            <StatCard accent="bg-rose-500" label="Duration" value={formatNumber(totals.duration, 2)} subvalue={to ? formatDate(to) : '—'} />
          </section>

          <section className="soft-panel overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 p-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Визуализация</div>
                <div className="mt-0.5 text-lg font-bold text-slate-950">
                  {meta.data?.metrics.find((x) => x.value === metric)?.label ?? metric}
                </div>
              </div>
              <div className="flex rounded-lg border border-slate-200 bg-slate-100 p-1">
                {CHART_OPTIONS.map(({ type, icon: Icon, label }) => (
                  <button
                    key={type}
                    type="button"
                    title={label}
                    onClick={() => setChartType(type)}
                    className={clsx(
                      'flex h-9 w-9 items-center justify-center rounded-md text-sm transition',
                      chartType === type ? 'bg-slate-950 text-white shadow-sm' : 'text-slate-600 hover:bg-white hover:text-slate-950',
                    )}
                  >
                    <Icon className="h-4 w-4" />
                  </button>
                ))}
              </div>
            </div>

            {workbench.isLoading ? (
              <div className="flex h-96 items-center justify-center text-sm font-medium text-slate-500">Загрузка...</div>
            ) : rows.length === 0 ? (
              <div className="flex h-96 items-center justify-center text-sm font-medium text-slate-500">Нет данных</div>
            ) : chartType === 'table' ? (
              <AnalyticsTable rows={rows} metric={metric} cduTypeById={cduTypeById} />
            ) : (
              <div className="h-[420px] p-4">{chart}</div>
            )}
          </section>

          <section className="soft-panel overflow-hidden">
            <div className="flex items-center justify-between gap-3 border-b border-slate-200 p-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Детализация</div>
                <div className="font-bold text-slate-950">Таблица данных</div>
              </div>
              <div className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-bold text-emerald-800">
                {formatNumber(rows.length, 0)}
              </div>
            </div>
            <AnalyticsTable rows={rows} metric={metric} compact cduTypeById={cduTypeById} />
          </section>
        </main>
      </section>
    </div>
  )
}

function HeaderStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-r border-white/10 px-5 py-3 last:border-r-0">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 truncate text-sm font-bold text-white">{value}</div>
    </div>
  )
}

function FilterBlock({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children: ReactNode }) {
  return (
    <section>
      <div className="mb-2 flex items-center gap-2 text-sm font-bold text-slate-800">
        <Icon className="h-4 w-4 text-emerald-600" />
        {title}
      </div>
      {children}
    </section>
  )
}

function CheckboxPill({ checked, label, onChange }: { checked: boolean; label: string; onChange: () => void }) {
  return (
    <label className={clsx('flex min-h-10 items-center gap-2 rounded-lg border px-2.5 py-2 text-sm font-medium transition', checked ? 'border-emerald-500 bg-emerald-50 text-emerald-800' : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50')}>
      <input type="checkbox" checked={checked} onChange={onChange} className="h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500" />
      <span className="truncate">{label}</span>
    </label>
  )
}

function CheckboxRow({ checked, label, onChange }: { checked: boolean; label: string; onChange: () => void }) {
  return (
    <label className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-slate-700 transition hover:bg-slate-100">
      <input type="checkbox" checked={checked} onChange={onChange} className="h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500" />
      <span className="truncate">{label}</span>
    </label>
  )
}

function MultiSelectList({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <div className="label">{title}</div>
      <div className="max-h-36 space-y-0.5 overflow-auto rounded-lg border border-slate-200 bg-slate-50/70 p-1">
        {children}
      </div>
    </div>
  )
}

function StatCard({ accent, label, value, subvalue }: { accent: string; label: string; value: string; subvalue: string }) {
  return (
    <div className="analytics-stat">
      <div className={clsx('absolute inset-y-0 left-0 w-1', accent)} />
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate text-2xl font-black text-slate-950">{value}</div>
      <div className="mt-1 truncate text-xs font-medium text-slate-500">{subvalue}</div>
    </div>
  )
}

function AnalyticsTable({
  rows,
  metric,
  cduTypeById,
  compact = false,
}: {
  rows: WorkbenchRow[]
  metric: string
  cduTypeById: Map<number, string>
  compact?: boolean
}) {
  return (
    <div className={clsx('overflow-auto', compact ? 'max-h-96' : 'h-96')}>
      <table className="min-w-full text-sm">
        <thead className="sticky top-0 z-10 bg-slate-950">
          <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-200">
            <th className="px-3 py-2">Дата</th>
            <th className="px-3 py-2">ЧДУ</th>
            <th className="px-3 py-2">Тип</th>
            <th className="px-3 py-2">Категория</th>
            <th className="px-3 py-2">Инструмент</th>
            <th className="px-3 py-2 text-right">Метрика</th>
            <th className="px-3 py-2 text-right">MV</th>
            <th className="px-3 py-2 text-right">YTM</th>
            <th className="px-3 py-2 text-right">Duration</th>
            <th className="px-3 py-2 text-right">Кол-во</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {rows.map((row, i) => (
            <tr key={`${row.date}-${row.cdu_id}-${row.category}-${row.instrument}-${i}`} className="transition hover:bg-emerald-50/60">
              <td className="whitespace-nowrap px-3 py-2 text-slate-700">{row.date ? formatDate(row.date) : '—'}</td>
              <td className="whitespace-nowrap px-3 py-2 font-semibold text-slate-900">{row.cdu_short ?? row.cdu_name ?? '—'}</td>
              <td className="whitespace-nowrap px-3 py-2 text-slate-600">
                {(() => {
                  const type = row.portfolio_type ?? (row.cdu_id ? cduTypeById.get(row.cdu_id) : null)
                  return type ? PORTFOLIO_TYPE_RU[type] ?? type : '—'
                })()}
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-slate-700">{row.category ?? '—'}</td>
              <td className="min-w-56 px-3 py-2 text-slate-700">{row.instrument ?? '—'}</td>
              <td className="whitespace-nowrap px-3 py-2 text-right font-bold text-slate-950">{formatMetric(metric, row.metric_value)}</td>
              <td className="whitespace-nowrap px-3 py-2 text-right text-slate-700">{formatNumber(row.market_value, 0)}</td>
              <td className="whitespace-nowrap px-3 py-2 text-right text-slate-700">{formatPct(row.ytm)}</td>
              <td className="whitespace-nowrap px-3 py-2 text-right text-slate-700">{formatNumber(row.duration, 2)}</td>
              <td className="whitespace-nowrap px-3 py-2 text-right text-slate-700">{formatNumber(row.count, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
