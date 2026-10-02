import { type ReactNode, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  ArrowLeft,
  BookMarked,
  Building2,
  CalendarDays,
  ChevronDown,
  ChevronUp,
  Clock3,
  Coins,
  FileText,
  Filter,
  Fingerprint,
  Gauge,
  Hash,
  Eye,
  Landmark,
  Layers,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  WalletCards,
  X,
  type LucideIcon,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { CDU } from '@/lib/types'
import { useAuthStore } from '@/lib/auth'
import { useConfirm } from '@/lib/confirm'
import CouponScheduleEditor from '@/components/CouponScheduleEditor'
import ReferenceBook from '@/components/ReferenceBook'

// ─────────────── types ───────────────

interface Holding {
  id: number
  cdu_id: number | null
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

interface HoldingReference {
  isin: string
  nin: string | null
  ticker_kase: string | null
  instrument_name: string | null
  security_type: string | null
  issuer: string | null
  issuer_type: string | null
  bond_type: string | null
  coupon_rate_pct: number | null
  coupon_rate_text: string | null
  coupon_type: string | null
  frequency: number | null
  base: string | null
  base_code: string | null
  nominal: number | null
  start_date: string | null
  maturity_date: string | null
  last_coupon_date: string | null
  next_coupon_date: string | null
  quotation_type: string | null
  currency: string
  rating: string | null
  rating_source: string | null
  rating_agency: string | null
  source: string | null
  source_updated_at: string | null
  notes: string | null
  is_active: boolean
  updated_at: string | null
  updated_by: string | null
}

interface HoldingHistoryStats {
  operations_count?: number
  snapshots_count?: number
  first_date?: string | null
  last_date?: string | null
  buy_quantity?: number
  sell_quantity?: number
  net_trade_quantity?: number
  cash_flow_kzt?: number
}

interface HoldingHistoryEvent {
  id: number
  kind: 'TRADE'
  date: string
  trade_date: string | null
  value_date: string | null
  operation_type: string
  direction: string | null
  quantity: number | null
  signed_quantity: number
  face_value: number | null
  amount_kzt: number | null
  currency: string
  price: number | null
  ytm: number | null
  repo_rate_pct: number | null
  deal_id: string | null
  portfolio_code: string | null
  description: string | null
  is_manual: boolean
  is_synthetic: boolean
}

interface HoldingHistorySnapshot {
  id: number
  source: 'BOND_LOT' | 'REPO_LOT' | 'POSITION'
  source_label: string
  date: string
  trade_date: string | null
  quantity: number | null
  face_value: number | null
  price: number | null
  market_value: number | null
  ytm: number | null
  duration: number | null
  status: string | null
  portfolio_code: string | null
}

interface HoldingHistoryResponse {
  holding_id: number
  reference: HoldingReference | null
  stats: HoldingHistoryStats
  timeline: HoldingHistoryEvent[]
  snapshots: HoldingHistorySnapshot[]
}

interface ParamItem {
  label: string
  value: ReactNode
  wide?: boolean
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
  GOV_BONDS: 'bg-emerald-100 text-emerald-800 ring-emerald-200',
  AGENCY_BONDS: 'bg-cyan-100 text-cyan-800 ring-cyan-200',
  MFO_BONDS: 'bg-indigo-100 text-indigo-800 ring-indigo-200',
  FOREIGN_BONDS: 'bg-violet-100 text-violet-800 ring-violet-200',
  REVERSE_REPO: 'bg-amber-100 text-amber-800 ring-amber-200',
  DEPOSIT: 'bg-blue-100 text-blue-800 ring-blue-200',
  CASH: 'bg-slate-100 text-slate-700 ring-slate-200',
  OTHER: 'bg-slate-100 text-slate-700 ring-slate-200',
}

const CATEGORY_ACCENT: Record<string, {
  strip: string
  avatar: string
  icon: string
  soft: string
  dot: string
  border: string
}> = {
  GOV_BONDS: {
    strip: 'bg-emerald-600',
    avatar: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
    icon: 'bg-emerald-600 text-white',
    soft: 'bg-emerald-50 text-emerald-800 ring-emerald-100',
    dot: 'bg-emerald-500',
    border: 'border-emerald-200',
  },
  AGENCY_BONDS: {
    strip: 'bg-cyan-600',
    avatar: 'bg-cyan-50 text-cyan-700 ring-cyan-200',
    icon: 'bg-cyan-600 text-white',
    soft: 'bg-cyan-50 text-cyan-800 ring-cyan-100',
    dot: 'bg-cyan-500',
    border: 'border-cyan-200',
  },
  MFO_BONDS: {
    strip: 'bg-indigo-600',
    avatar: 'bg-indigo-50 text-indigo-700 ring-indigo-200',
    icon: 'bg-indigo-600 text-white',
    soft: 'bg-indigo-50 text-indigo-800 ring-indigo-100',
    dot: 'bg-indigo-500',
    border: 'border-indigo-200',
  },
  FOREIGN_BONDS: {
    strip: 'bg-violet-600',
    avatar: 'bg-violet-50 text-violet-700 ring-violet-200',
    icon: 'bg-violet-600 text-white',
    soft: 'bg-violet-50 text-violet-800 ring-violet-100',
    dot: 'bg-violet-500',
    border: 'border-violet-200',
  },
  REVERSE_REPO: {
    strip: 'bg-amber-500',
    avatar: 'bg-amber-50 text-amber-800 ring-amber-200',
    icon: 'bg-amber-500 text-white',
    soft: 'bg-amber-50 text-amber-800 ring-amber-100',
    dot: 'bg-amber-500',
    border: 'border-amber-200',
  },
  DEPOSIT: {
    strip: 'bg-blue-600',
    avatar: 'bg-blue-50 text-blue-700 ring-blue-200',
    icon: 'bg-blue-600 text-white',
    soft: 'bg-blue-50 text-blue-800 ring-blue-100',
    dot: 'bg-blue-500',
    border: 'border-blue-200',
  },
  CASH: {
    strip: 'bg-slate-500',
    avatar: 'bg-slate-100 text-slate-700 ring-slate-200',
    icon: 'bg-slate-700 text-white',
    soft: 'bg-slate-100 text-slate-700 ring-slate-200',
    dot: 'bg-slate-400',
    border: 'border-slate-200',
  },
  OTHER: {
    strip: 'bg-slate-500',
    avatar: 'bg-slate-100 text-slate-700 ring-slate-200',
    icon: 'bg-slate-700 text-white',
    soft: 'bg-slate-100 text-slate-700 ring-slate-200',
    dot: 'bg-slate-400',
    border: 'border-slate-200',
  },
}

const OPERATION_LABEL: Record<string, string> = {
  BUY: 'Покупка',
  SELL: 'Продажа',
  REPO_OPEN: 'Открытие REPO',
  REPO_CLOSE: 'Закрытие REPO',
  COUPON: 'Купон',
  REDEMPTION: 'Погашение',
  DEPOSIT_OPEN: 'Открытие депозита',
  DEPOSIT_CLOSE: 'Закрытие депозита',
  OTHER: 'Операция',
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
  return `${formatNumber(n / 1_000_000, 1)} млн`
}

function formatMoney(n: number | null | undefined, digits = 0): string {
  if (n == null || Number.isNaN(n)) return '—'
  return `${formatNumber(n, digits)} ₸`
}

function formatPctPlain(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return '—'
  return `${formatNumber(n, digits)}%`
}

function formatDate(v: string | null | undefined): string {
  if (!v) return '—'
  const d = new Date(`${v}T00:00:00`)
  if (Number.isNaN(d.valueOf())) return v
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

function formatDateTime(v: string | null | undefined): string {
  if (!v) return '—'
  const d = new Date(v)
  if (Number.isNaN(d.valueOf())) return v
  return d.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function sourceLabel(source: Holding['source']) {
  return source === 'MANUAL' ? 'Ручной' : 'Авто'
}

function categoryAccent(category: string | null | undefined) {
  return CATEGORY_ACCENT[category ?? 'OTHER'] ?? CATEGORY_ACCENT.OTHER
}

function profileInitials(h: Holding): string {
  const raw = (h.instrument_code || h.isin || h.instrument_name || 'ЦБ').trim()
  const clean = raw.replace(/[^A-Za-zА-Яа-я0-9]/g, '')
  if (!clean) return 'ЦБ'
  return clean.slice(0, 3).toUpperCase()
}

function positionStatus(h: Holding) {
  if ((h.quantity ?? 0) > 0) {
    return { label: 'Активная позиция', tone: 'bg-emerald-50 text-emerald-700 ring-emerald-100', dot: 'bg-emerald-500' }
  }
  if ((h.quantity ?? 0) < 0) {
    return { label: 'Короткая позиция', tone: 'bg-red-50 text-red-700 ring-red-100', dot: 'bg-red-500' }
  }
  return { label: 'Историческая бумага', tone: 'bg-slate-100 text-slate-700 ring-slate-200', dot: 'bg-slate-400' }
}

function profileFacts(h: Holding): Array<{ icon: LucideIcon; label: string; value: string; sub?: string; mono?: boolean }> {
  return [
    { icon: WalletCards, label: 'MV', value: formatMillions(h.market_value), sub: 'рыночная стоимость' },
    { icon: Gauge, label: 'Цена KASE', value: formatNumber(h.last_kase_price, 4), sub: formatDate(h.last_kase_date), mono: true },
    { icon: CalendarDays, label: 'Погашение', value: formatDate(h.maturity_date), sub: formatPctPlain(h.coupon_rate_pct) },
  ]
}

// ─────────────── page ───────────────

export default function SecuritiesPage() {
  const qc = useQueryClient()
  const confirm = useConfirm()
  const canWrite = useAuthStore((s) => s.can('securities.edit'))

  const [cduFilter, setCduFilter] = useState<number | ''>('')
  const [categoryFilter, setCategoryFilter] = useState<string>('')
  const [sourceFilter, setSourceFilter] = useState<'' | 'AUTO' | 'MANUAL'>('')
  const [onlyWithQty, setOnlyWithQty] = useState(true)
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<Holding | null>(null)
  const [creating, setCreating] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [profileHolding, setProfileHolding] = useState<Holding | null>(null)
  const [view, setView] = useState<'positions' | 'issues'>('positions')

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
      if (expandedId) qc.invalidateQueries({ queryKey: ['security-history', expandedId] })
    },
    onError: () => toast.error('Не удалось синхронизировать справочник'),
  })

  const remove = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/securities/${id}`)).data,
    onSuccess: () => {
      toast.success('Запись удалена')
      qc.invalidateQueries({ queryKey: ['securities'] })
      qc.invalidateQueries({ queryKey: ['securities-summary'] })
      setExpandedId(null)
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

  if (profileHolding) {
    return (
      <div className="space-y-5">
        <SecurityProfilePage
          h={profileHolding}
          canWrite={canWrite}
          onBack={() => setProfileHolding(null)}
          onEdit={() => setEditing(profileHolding)}
          onDelete={async () => {
            const { confirmed } = await confirm({
              title: 'Удалить запись из справочника?',
              description: `Позиция ${profileHolding.isin} будет удалена безвозвратно.`,
              tone: 'danger',
              confirmLabel: 'Удалить',
            })
            if (confirmed) {
              remove.mutate(profileHolding.id)
              setProfileHolding(null)
            }
          }}
        />

        {editing && (
          <HoldingFormModal
            existing={editing}
            cdus={cdusQ.data ?? []}
            onClose={closeModal}
            onSaved={() => {
              qc.invalidateQueries({ queryKey: ['securities'] })
              qc.invalidateQueries({ queryKey: ['securities-summary'] })
              qc.invalidateQueries({ queryKey: ['security-history', editing.id] })
              closeModal()
            }}
          />
        )}
      </div>
    )
  }

  const viewSwitch = (
    <div className="flex w-fit gap-1 rounded-xl bg-slate-100 p-1">
      {([['positions', 'Позиции ЧДУ'], ['issues', 'Выпуски и графики купонов']] as const).map(([key, label]) => (
        <button key={key} type="button" onClick={() => setView(key)}
          className={`rounded-lg px-4 py-1.5 text-sm font-semibold ${view === key ? 'bg-white text-emerald-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>
          {label}
        </button>
      ))}
    </div>
  )

  if (view === 'issues') {
    return (
      <div className="space-y-5">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-3xl font-black">Справочник ценных бумаг</h1>
            <p className="text-sm text-slate-500">Все выпуски, которые используют расчёты: параметры, график купонных выплат, загрузка с KASE</p>
          </div>
          {viewSwitch}
        </header>
        <ReferenceBook canWrite={canWrite} />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {viewSwitch}
      <header className="overflow-hidden rounded-lg border border-slate-800 bg-slate-950 text-white shadow-card">
        <div className="flex flex-wrap items-start justify-between gap-4 p-5">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1 text-xs font-semibold text-emerald-200">
              <BookMarked className="h-3.5 w-3.5" />
              {formatNumber(list.length, 0)} / {formatNumber(summaryQ.data?.total_count ?? 0, 0)}
            </div>
            <h1 className="text-3xl font-black tracking-normal">Справочник ценных бумаг</h1>
          </div>
          {canWrite && (
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={() => sync.mutate()}
                disabled={sync.isPending}
                className="btn border border-white/10 bg-white text-slate-950 hover:bg-emerald-50"
                title="Полная пересборка из активных Trade-записей"
              >
                <RefreshCw className={`h-4 w-4 ${sync.isPending ? 'animate-spin' : ''}`} />
                Синхронизировать
              </button>
              <button onClick={() => setCreating(true)} className="btn bg-emerald-500 text-white hover:bg-emerald-400">
                <Plus className="h-4 w-4" />
                Добавить вручную
              </button>
            </div>
          )}
        </div>
        <div className="grid grid-cols-2 border-t border-white/10 md:grid-cols-4">
          <HeaderStat label="Рыночная стоимость" value={formatMillions(totalMV)} />
          <HeaderStat label="Показано" value={formatMillions(totalShownMV)} />
          <HeaderStat label="Авто" value={formatNumber(summaryQ.data?.auto_count ?? 0, 0)} />
          <HeaderStat label="Ручные" value={formatNumber(summaryQ.data?.manual_count ?? 0, 0)} />
        </div>
      </header>

      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard icon={WalletCards} label="Всего записей" value={summaryQ.data?.total_count ?? 0} />
        <KpiCard icon={Coins} label="Портфель" value={formatMillions(totalMV)} highlight />
        <KpiCard icon={Activity} label="Показано" value={list.length} />
        <KpiCard icon={Landmark} label="Категорий" value={summaryQ.data?.by_category.length ?? 0} />
      </section>

      {summaryQ.data && summaryQ.data.by_category.length > 0 && (
        <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-card">
          <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
            Категории
          </div>
          <div className="flex flex-wrap gap-2">
            <CategoryButton
              active={categoryFilter === ''}
              label="Все"
              count={summaryQ.data.total_count}
              onClick={() => setCategoryFilter('')}
            />
            {summaryQ.data.by_category.map((c) => (
              <CategoryButton
                key={c.category}
                active={categoryFilter === c.category}
                label={CATEGORY_LABEL[c.category] ?? c.category}
                count={c.count}
                color={CATEGORY_COLOR[c.category] ?? CATEGORY_COLOR.OTHER}
                onClick={() => setCategoryFilter(c.category)}
              />
            ))}
          </div>
        </section>
      )}

      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-card">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
          <Filter className="h-3.5 w-3.5 text-emerald-600" />
          Фильтры
        </div>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(260px,1.6fr)_minmax(190px,1fr)_minmax(170px,0.9fr)_auto]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="ISIN, тикер или название..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="input h-10 pl-9"
            />
          </div>
          <select
            className="input h-10"
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
            className="input h-10"
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value as any)}
          >
            <option value="">Все источники</option>
            <option value="AUTO">Авто (из Trade)</option>
            <option value="MANUAL">Ручные</option>
          </select>
          <label className="flex h-10 items-center gap-2 rounded-lg border border-slate-200 bg-slate-50/80 px-3 text-sm font-medium text-slate-700">
            <input
              type="checkbox"
              checked={onlyWithQty}
              onChange={(e) => setOnlyWithQty(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
            />
            qty &gt; 0
          </label>
        </div>
        {(cduFilter || categoryFilter || sourceFilter || search || !onlyWithQty) && (
          <button
            onClick={resetFilters}
            className="mt-3 text-xs font-semibold text-slate-500 underline-offset-2 hover:text-emerald-700 hover:underline"
          >
            Сбросить фильтры
          </button>
        )}
      </section>

      {listQ.isLoading ? (
        <section className="space-y-2 rounded-lg border border-slate-200 bg-white p-2 shadow-card">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-lg bg-gradient-to-r from-slate-100 via-white to-slate-100" />
          ))}
        </section>
      ) : list.length === 0 ? (
        <section className="flex min-h-64 items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white text-sm font-medium text-slate-500">
          Записей не найдено
        </section>
      ) : (
        <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-card">
          <div className="hidden grid-cols-[minmax(260px,1.6fr)_minmax(150px,0.7fr)_minmax(150px,0.7fr)_minmax(130px,0.55fr)_116px] gap-3 border-b border-slate-200 bg-slate-950 px-4 py-3 text-xs font-bold uppercase tracking-wide text-slate-300 lg:grid">
            <div>Наименование</div>
            <div>Тип</div>
            <div className="text-right">Общая сумма</div>
            <div className="text-right">Количество</div>
            <div className="text-right">Действие</div>
          </div>
          {list.map((h) => (
            <SecurityListRow
              key={h.id}
              h={h}
              expanded={expandedId === h.id}
              onToggle={() => setExpandedId((id) => (id === h.id ? null : h.id))}
              onShow={() => setProfileHolding(h)}
            />
          ))}
        </section>
      )}

      {(creating || editing) && (
        <HoldingFormModal
          existing={editing}
          cdus={cdusQ.data ?? []}
          onClose={closeModal}
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ['securities'] })
            qc.invalidateQueries({ queryKey: ['securities-summary'] })
            if (editing) qc.invalidateQueries({ queryKey: ['security-history', editing.id] })
            closeModal()
          }}
        />
      )}
    </div>
  )
}

// ─────────────── cards ───────────────

function SecurityListRow({
  h,
  expanded,
  onToggle,
  onShow,
}: {
  h: Holding
  expanded: boolean
  onToggle: () => void
  onShow: () => void
}) {
  const accent = categoryAccent(h.category)
  const status = positionStatus(h)

  return (
    <div className="border-b border-slate-100 last:border-b-0">
      <div
        role="button"
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onToggle()
          }
        }}
        className={`grid w-full grid-cols-1 gap-3 px-4 py-3 text-left transition hover:bg-slate-50 lg:grid-cols-[minmax(260px,1.6fr)_minmax(150px,0.7fr)_minmax(150px,0.7fr)_minmax(130px,0.55fr)_116px] lg:items-center ${
          expanded ? 'bg-emerald-50/40' : 'bg-white'
        }`}
      >
        <div className="flex min-w-0 items-center gap-3">
          <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-xs font-black ring-1 ${accent.avatar}`}>
            {profileInitials(h)}
          </div>
          <div className="min-w-0">
            <div className="line-clamp-1 font-bold text-slate-950">{h.instrument_name ?? h.isin}</div>
            <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-xs font-medium text-slate-500">
              <span className="font-mono">{h.isin}</span>
              {h.instrument_code && <span className="font-mono">{h.instrument_code}</span>}
              <span>{h.cdu_name ?? (h.cdu_id ? `#${h.cdu_id}` : "Справочник (без ЧДУ)")}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between gap-2 lg:block">
          <span className="text-xs font-bold uppercase text-slate-400 lg:hidden">Тип</span>
          <span className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-bold ring-1 ${CATEGORY_COLOR[h.category ?? 'OTHER'] ?? CATEGORY_COLOR.OTHER}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${accent.dot}`} />
            {CATEGORY_LABEL[h.category ?? 'OTHER'] ?? '—'}
          </span>
        </div>

        <div className="flex items-center justify-between gap-2 lg:block lg:text-right">
          <span className="text-xs font-bold uppercase text-slate-400 lg:hidden">Общая сумма</span>
          <span className="font-black text-slate-950">{formatMillions(h.market_value)}</span>
        </div>

        <div className="flex items-center justify-between gap-2 lg:block lg:text-right">
          <span className="text-xs font-bold uppercase text-slate-400 lg:hidden">Количество</span>
          <span className="font-mono font-bold text-slate-800">{formatNumber(h.quantity, 0)}</span>
        </div>

        <div className="flex items-center justify-between gap-2 lg:justify-end">
          <span className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-bold ring-1 lg:hidden ${status.tone}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${status.dot}`} />
            {status.label}
          </span>
          <span
            role="button"
            tabIndex={0}
            onClick={(e) => {
              e.stopPropagation()
              onShow()
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                e.stopPropagation()
                onShow()
              }
            }}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 text-xs font-bold text-white transition hover:bg-emerald-700"
          >
            <Eye className="h-3.5 w-3.5" />
            Показать
          </span>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-slate-100 bg-slate-50 px-4 py-4">
          <div className="grid gap-3 md:grid-cols-4">
            <BriefInfo icon={Fingerprint} label="ISIN / тикер" value={h.instrument_code ? `${h.isin} · ${h.instrument_code}` : h.isin} mono />
            <BriefInfo icon={Gauge} label="Цена KASE" value={formatNumber(h.last_kase_price, 4)} sub={formatDate(h.last_kase_date)} mono />
            <BriefInfo icon={CalendarDays} label="Купон / погашение" value={formatPctPlain(h.coupon_rate_pct)} sub={formatDate(h.maturity_date)} />
          </div>
        </div>
      )}
    </div>
  )
}

function SecurityProfilePage({
  h,
  canWrite,
  onBack,
  onEdit,
  onDelete,
}: {
  h: Holding
  canWrite: boolean
  onBack: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const catColor = CATEGORY_COLOR[h.category ?? 'OTHER'] ?? CATEGORY_COLOR.OTHER
  const accent = categoryAccent(h.category)
  const status = positionStatus(h)
  const facts = profileFacts(h)
  const historyQ = useQuery<HoldingHistoryResponse>({
    queryKey: ['security-history', h.id],
    queryFn: async () => (await api.get(`/securities/${h.id}/history`)).data,
  })

  const history = historyQ.data
  const chartData = useMemo(() => buildChartData(history?.snapshots ?? []), [history?.snapshots])
  const currentParams = useMemo(() => buildCurrentParams(h), [h])
  const referenceParams = useMemo(() => buildReferenceParams(history?.reference), [history?.reference])

  return (
    <article className={`overflow-hidden rounded-lg border bg-white shadow-card ${accent.border}`}>
      <div className={`h-1.5 ${accent.strip}`} />

      <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-5 py-3">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-bold text-slate-700 transition hover:bg-slate-50 hover:text-slate-950"
        >
          <ArrowLeft className="h-4 w-4" />
          Назад к списку
        </button>
        <div className="flex items-center gap-1">
          {canWrite && (
            <>
              <button
                onClick={onEdit}
                className="flex h-9 w-9 items-center justify-center rounded-md text-slate-500 transition hover:bg-emerald-50 hover:text-emerald-700"
                title="Редактировать"
              >
                <Pencil className="h-4 w-4" />
              </button>
              {h.source === 'MANUAL' && (
                <button
                  onClick={onDelete}
                  className="flex h-9 w-9 items-center justify-center rounded-md text-slate-500 transition hover:bg-red-50 hover:text-red-600"
                  title="Удалить"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </>
          )}
        </div>
      </div>

      <div className="border-b border-slate-100">
        <div className="grid gap-0 lg:grid-cols-[1fr_230px]">
          <div className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="flex min-w-0 gap-4">
                <div className={`relative flex h-16 w-16 shrink-0 items-center justify-center rounded-lg text-lg font-black ring-1 ${accent.avatar}`}>
                  {profileInitials(h)}
                  <span className={`absolute -bottom-1 -right-1 flex h-5 w-5 items-center justify-center rounded-md ring-4 ring-white ${accent.icon}`}>
                    <Fingerprint className="h-3 w-3" />
                  </span>
                </div>

                <div className="min-w-0">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <span className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ${catColor}`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${accent.dot}`} />
                      {CATEGORY_LABEL[h.category ?? 'OTHER'] ?? '—'}
                    </span>
                    <span className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ${status.tone}`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${status.dot}`} />
                      {status.label}
                    </span>
                    <span className={`inline-flex rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ${
                      h.source === 'MANUAL'
                        ? 'bg-amber-50 text-amber-800 ring-amber-200'
                        : 'bg-slate-50 text-slate-600 ring-slate-200'
                    }`}>
                      {sourceLabel(h.source)}
                    </span>
                  </div>

                  <h2 className="line-clamp-2 text-xl font-black leading-snug text-slate-950" title={h.instrument_name ?? h.isin}>
                    {h.instrument_name ?? h.isin}
                  </h2>

                  <div className="mt-3 grid gap-2 text-xs font-medium text-slate-600 sm:grid-cols-3">
                    <IdentityPill icon={Fingerprint} label="ISIN" value={h.isin} mono />
                    <IdentityPill icon={Hash} label="Тикер" value={h.instrument_code ?? '—'} mono />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="border-t border-slate-100 bg-slate-50/70 p-5 lg:border-l lg:border-t-0">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-bold uppercase text-slate-500">Профиль позиции</div>
              <span className={`rounded-md px-2 py-0.5 text-xs font-black ring-1 ${accent.soft}`}>
                {h.currency}
              </span>
            </div>
            <div className="mt-3 text-2xl font-black text-slate-950">{formatMillions(h.market_value)}</div>
            <div className="mt-1 text-xs font-medium text-slate-500">по последней доступной оценке</div>
            <div className="mt-4 space-y-2">
              <ProfileLine label="KASE" value={formatNumber(h.last_kase_price, 4)} />
              <ProfileLine label="Синхронизация" value={formatDateTime(h.last_synced_at)} />
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-px bg-slate-100 md:grid-cols-4">
          {facts.map((fact) => (
            <ProfileFact key={fact.label} {...fact} />
          ))}
        </div>
      </div>

      <div className="space-y-5 bg-white p-5">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <MiniStat icon={CalendarDays} label="В портфеле с" value={formatDate(history?.stats.first_date)} />
            <MiniStat icon={Clock3} label="Последняя операция" value={formatDate(history?.stats.last_date)} />
            <MiniStat icon={Activity} label="Операций" value={formatNumber(history?.stats.operations_count ?? 0, 0)} />
            <MiniStat icon={FileText} label="Срезов" value={formatNumber(history?.stats.snapshots_count ?? 0, 0)} />
          </div>

          {historyQ.isLoading ? (
            <div className="flex h-56 items-center justify-center rounded-lg bg-slate-50 text-sm font-medium text-slate-500">
              Загрузка истории...
            </div>
          ) : historyQ.isError ? (
            <div className="rounded-lg bg-red-50 px-4 py-3 text-sm font-medium text-red-700 ring-1 ring-red-100">
              Не удалось загрузить историю
            </div>
          ) : (
            <>
              <section>
                <SectionTitle icon={ShieldCheck} title="Профиль бумаги" />
                <ParamGrid items={currentParams} />
              </section>

              {referenceParams.length > 0 && (
                <section>
                  <SectionTitle icon={BookMarked} title="Паспорт выпуска" />
                  <ParamGrid items={referenceParams} />
                </section>
              )}

              <CouponScheduleEditor isin={h.isin} canEdit={canWrite} />

              {chartData.length > 0 && (
                <section>
                  <SectionTitle icon={Activity} title="Динамика в портфеле" />
                  <div className="h-56 rounded-lg bg-slate-50 p-3 ring-1 ring-slate-100">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={chartData}>
                        <defs>
                          <linearGradient id={`securityMv-${h.id}`} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#059669" stopOpacity={0.28} />
                            <stop offset="95%" stopColor="#059669" stopOpacity={0.02} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#64748b' }} tickFormatter={formatDate} />
                        <YAxis tick={{ fontSize: 11, fill: '#64748b' }} tickFormatter={(v) => `${(Number(v) / 1_000_000).toFixed(0)} млн`} />
                        <Tooltip
                          formatter={(value: unknown) => formatMoney(Number(value), 0)}
                          labelFormatter={(label) => formatDate(String(label))}
                        />
                        <Area
                          type="monotone"
                          dataKey="market_value"
                          stroke="#059669"
                          strokeWidth={2.5}
                          fill={`url(#securityMv-${h.id})`}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </section>
              )}

              <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <div>
                  <SectionTitle icon={Activity} title="Операции" />
                  <TimelineList events={history?.timeline ?? []} />
                </div>
                <div>
                  <SectionTitle icon={Layers} title="Срезы портфеля" />
                  <SnapshotList snapshots={history?.snapshots ?? []} />
                </div>
              </section>
            </>
          )}
      </div>
    </article>
  )
}

function buildCurrentParams(h: Holding): ParamItem[] {
  return [
    { label: 'Источник', value: sourceLabel(h.source) },
    { label: 'ISIN / ключ', value: <span className="font-mono">{h.isin}</span> },
    { label: 'Тикер', value: h.instrument_code ? <span className="font-mono">{h.instrument_code}</span> : '—' },
    { label: 'Название', value: h.instrument_name ?? '—', wide: true },
    { label: 'Категория', value: CATEGORY_LABEL[h.category ?? 'OTHER'] ?? h.category ?? '—' },
    { label: 'Валюта', value: h.currency },
    { label: 'Цена KASE', value: formatNumber(h.last_kase_price, 4) },
    { label: 'Дата KASE', value: formatDate(h.last_kase_date) },
    { label: 'Рыночная стоимость', value: formatMoney(h.market_value) },
    { label: 'Номинал на ед.', value: formatNumber(h.nominal_per_unit, 2) },
    { label: 'Купон', value: formatPctPlain(h.coupon_rate_pct) },
    { label: 'Дата погашения', value: formatDate(h.maturity_date) },
    { label: 'Синхронизация', value: formatDateTime(h.last_synced_at) },
    { label: 'Обновлено', value: formatDateTime(h.updated_at) },
    { label: 'Обновил', value: h.updated_by ?? '—' },
    { label: 'Заметки', value: h.notes ?? '—', wide: true },
  ]
}

function buildReferenceParams(ref: HoldingReference | null | undefined): ParamItem[] {
  if (!ref) return []
  return [
    { label: 'ISIN', value: <span className="font-mono">{ref.isin}</span> },
    { label: 'НИН', value: ref.nin ?? '—' },
    { label: 'Тикер KASE', value: ref.ticker_kase ? <span className="font-mono">{ref.ticker_kase}</span> : '—' },
    { label: 'Эмитент', value: ref.issuer ?? '—' },
    { label: 'Тип эмитента', value: ref.issuer_type ?? '—' },
    { label: 'Наименование', value: ref.instrument_name ?? '—', wide: true },
    { label: 'Тип ценной бумаги', value: ref.security_type ?? '—' },
    { label: 'Тип выпуска', value: ref.bond_type ?? '—' },
    { label: 'Купон', value: ref.coupon_rate_text ?? formatPctPlain(ref.coupon_rate_pct) },
    { label: 'Тип купона', value: ref.coupon_type ?? '—' },
    { label: 'Частота', value: ref.frequency ?? '—' },
    { label: 'База', value: ref.base ?? ref.base_code ?? '—' },
    { label: 'Номинал', value: formatNumber(ref.nominal, 2) },
    { label: 'Валюта', value: ref.currency },
    { label: 'Предмет котирования', value: ref.quotation_type ?? '—' },
    { label: 'Дата начала', value: formatDate(ref.start_date) },
    { label: 'Дата погашения', value: formatDate(ref.maturity_date) },
    { label: 'Последний купон', value: formatDate(ref.last_coupon_date) },
    { label: 'Следующий купон', value: formatDate(ref.next_coupon_date) },
    { label: 'Рейтинг эмитента', value: ref.rating ?? '—' },
    { label: 'Источник рейтинга', value: ref.rating_source ?? '—', wide: true },
    { label: 'Рейтинговое агентство', value: ref.rating_agency ?? '—' },
    { label: 'Источник данных', value: ref.source ?? '—' },
    { label: 'Дата загрузки источника', value: formatDateTime(ref.source_updated_at) },
    { label: 'Статус', value: ref.is_active ? 'Активен' : 'Неактивен' },
    { label: 'Обновлено', value: formatDateTime(ref.updated_at) },
    { label: 'Обновил', value: ref.updated_by ?? '—' },
    { label: 'Заметки', value: ref.notes ?? '—', wide: true },
  ]
}

function buildChartData(snapshots: HoldingHistorySnapshot[]) {
  const grouped = new Map<string, { date: string; market_value: number; quantity: number; hasPosition: boolean }>()
  for (const row of snapshots) {
    const current = grouped.get(row.date) ?? {
      date: row.date,
      market_value: 0,
      quantity: 0,
      hasPosition: false,
    }
    const isPosition = row.source === 'POSITION'
    if (isPosition && !current.hasPosition) {
      current.market_value = 0
      current.quantity = 0
      current.hasPosition = true
    }
    if (!current.hasPosition || isPosition) {
      current.market_value += row.market_value ?? 0
      current.quantity += row.quantity ?? 0
    }
    grouped.set(row.date, current)
  }
  return Array.from(grouped.values())
    .filter((row) => row.market_value !== 0 || row.quantity !== 0)
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(-32)
}

function HeaderStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-r border-white/10 px-5 py-3 last:border-r-0">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 truncate text-sm font-bold text-white">{value}</div>
    </div>
  )
}

function KpiCard({
  icon: Icon,
  label,
  value,
  highlight,
}: {
  icon: typeof WalletCards
  label: string
  value: string | number
  highlight?: boolean
}) {
  return (
    <div
      className={`group relative overflow-hidden rounded-2xl border bg-white p-4 shadow-card transition-all duration-300 hover:-translate-y-1 hover:shadow-card-hover ${
        highlight ? 'border-emerald-200' : 'border-slate-200'
      }`}
    >
      <div
        className={`absolute inset-x-0 top-0 h-1 bg-gradient-to-r ${
          highlight ? 'from-emerald-500 to-teal-400' : 'from-slate-200 to-slate-100'
        }`}
      />
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">{label}</div>
        <div
          className={`flex h-9 w-9 items-center justify-center rounded-xl transition-transform duration-300 group-hover:scale-110 ${
            highlight ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-500'
          }`}
        >
          <Icon className="h-4 w-4" />
        </div>
      </div>
      <div className={`mt-2 truncate text-2xl font-black ${highlight ? 'text-emerald-700' : 'text-slate-950'}`}>
        {value}
      </div>
    </div>
  )
}

function CategoryButton({
  active,
  label,
  count,
  color,
  onClick,
}: {
  active: boolean
  label: string
  count: number
  color?: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-3 py-1.5 text-xs font-semibold ring-1 transition ${
        active
          ? 'bg-slate-950 text-white ring-slate-950'
          : color ?? 'bg-white text-slate-700 ring-slate-200 hover:bg-slate-50'
      }`}
    >
      {label}
      <span className="ml-1.5 opacity-70">· {formatNumber(count, 0)}</span>
    </button>
  )
}

function IdentityPill({
  icon: Icon,
  label,
  value,
  mono,
}: {
  icon: LucideIcon
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="flex min-h-10 items-center gap-2 rounded-lg bg-slate-50 px-2.5 py-2 ring-1 ring-slate-100">
      <Icon className="h-3.5 w-3.5 shrink-0 text-slate-400" />
      <div className="min-w-0">
        <div className="text-[10px] font-bold uppercase text-slate-400">{label}</div>
        <div className={`truncate text-xs font-bold text-slate-800 ${mono ? 'font-mono' : ''}`}>{value}</div>
      </div>
    </div>
  )
}

function BriefInfo({
  icon: Icon,
  label,
  value,
  sub,
  mono,
}: {
  icon: LucideIcon
  label: string
  value: string
  sub?: string
  mono?: boolean
}) {
  return (
    <div className="rounded-lg bg-white p-3 ring-1 ring-slate-200">
      <div className="flex items-center gap-2 text-[11px] font-bold uppercase text-slate-500">
        <Icon className="h-3.5 w-3.5 text-emerald-600" />
        {label}
      </div>
      <div className={`mt-1 truncate text-sm font-black text-slate-950 ${mono ? 'font-mono' : ''}`}>{value}</div>
      {sub && <div className="mt-0.5 truncate text-xs font-medium text-slate-500">{sub}</div>}
    </div>
  )
}

function ProfileLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 text-xs">
      <span className="font-semibold text-slate-500">{label}</span>
      <span className="truncate text-right font-bold text-slate-900">{value}</span>
    </div>
  )
}

function ProfileFact({
  icon: Icon,
  label,
  value,
  sub,
  mono,
}: {
  icon: LucideIcon
  label: string
  value: string
  sub?: string
  mono?: boolean
}) {
  return (
    <div className="min-h-[92px] bg-white p-3">
      <div className="flex items-center gap-2 text-[11px] font-bold uppercase text-slate-500">
        <Icon className="h-3.5 w-3.5 text-slate-400" />
        {label}
      </div>
      <div className={`mt-2 truncate text-base font-black text-slate-950 ${mono ? 'font-mono' : ''}`}>{value}</div>
      {sub && <div className="mt-1 truncate text-[11px] font-semibold text-slate-500">{sub}</div>}
    </div>
  )
}

function MiniStat({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon
  label: string
  value: string
}) {
  return (
    <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-100">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase text-slate-500">
        <Icon className="h-3.5 w-3.5 text-emerald-600" />
        {label}
      </div>
      <div className="mt-1 truncate text-sm font-black text-slate-950">{value}</div>
    </div>
  )
}

function SectionTitle({ icon: Icon, title }: { icon: LucideIcon; title: string }) {
  return (
    <div className="mb-2 flex items-center gap-2 text-sm font-black text-slate-950">
      <Icon className="h-4 w-4 text-emerald-600" />
      {title}
    </div>
  )
}

function ParamGrid({ items }: { items: ParamItem[] }) {
  return (
    <div className="grid grid-cols-1 gap-px overflow-hidden rounded-lg bg-slate-100 ring-1 ring-slate-200 md:grid-cols-2">
      {items.map((item) => (
        <div
          key={item.label}
          className={`bg-white px-3 py-2.5 ${
            item.wide ? 'md:col-span-2' : ''
          }`}
        >
          <div className="text-[11px] font-semibold uppercase text-slate-500">{item.label}</div>
          <div className="mt-0.5 break-words text-sm font-semibold text-slate-900">{item.value}</div>
        </div>
      ))}
    </div>
  )
}

function TimelineList({ events }: { events: HoldingHistoryEvent[] }) {
  if (!events.length) {
    return (
      <div className="flex h-40 items-center justify-center rounded-lg bg-slate-50 text-sm font-medium text-slate-500 ring-1 ring-slate-100">
        Операций нет
      </div>
    )
  }
  return (
    <div className="max-h-80 overflow-auto rounded-lg bg-slate-50 p-2 ring-1 ring-slate-200">
      {events.map((event) => (
        <div key={event.id} className="relative mb-2 rounded-lg bg-white p-3 shadow-sm ring-1 ring-slate-100 last:mb-0">
          <div className={`absolute left-0 top-3 h-10 w-1 rounded-r ${event.signed_quantity < 0 ? 'bg-red-400' : 'bg-emerald-500'}`} />
          <div className="flex items-start justify-between gap-3">
            <div className="pl-2">
              <div className="text-sm font-black text-slate-950">
                {OPERATION_LABEL[event.operation_type] ?? event.operation_type}
              </div>
              <div className="mt-0.5 text-xs font-medium text-slate-500">
                {formatDate(event.date)}
                {event.deal_id ? ` · ${event.deal_id}` : ''}
              </div>
            </div>
            <div className={`rounded-md px-2 py-0.5 text-xs font-bold ${
              event.signed_quantity < 0 ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-700'
            }`}>
              {event.signed_quantity < 0 ? '' : '+'}{formatNumber(event.signed_quantity, 0)}
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 pl-2 text-xs text-slate-600">
            <EventMetric label="Цена" value={formatNumber(event.price, 4)} />
            <EventMetric label="Сумма" value={formatMoney(event.amount_kzt)} />
            <EventMetric label="YTM" value={formatPctPlain(event.ytm)} />
            <EventMetric label="Номинал" value={formatNumber(event.face_value, 0)} />
          </div>
          {event.description && (
            <div className="mt-2 line-clamp-2 pl-2 text-xs text-slate-500">{event.description}</div>
          )}
        </div>
      ))}
    </div>
  )
}

function SnapshotList({ snapshots }: { snapshots: HoldingHistorySnapshot[] }) {
  if (!snapshots.length) {
    return (
      <div className="flex h-40 items-center justify-center rounded-lg bg-slate-50 text-sm font-medium text-slate-500 ring-1 ring-slate-100">
        Срезов нет
      </div>
    )
  }
  return (
    <div className="max-h-80 overflow-auto rounded-lg bg-slate-50 p-2 ring-1 ring-slate-200">
      {snapshots.map((snapshot) => (
        <div key={`${snapshot.source}-${snapshot.id}`} className="mb-2 rounded-lg bg-white p-3 shadow-sm ring-1 ring-slate-100 last:mb-0">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-sm font-black text-slate-950">{snapshot.source_label}</div>
              <div className="mt-0.5 text-xs font-medium text-slate-500">
                {formatDate(snapshot.date)}
                {snapshot.status ? ` · ${snapshot.status}` : ''}
              </div>
            </div>
            <div className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-bold text-slate-700">
              {formatMillions(snapshot.market_value)}
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-600">
            <EventMetric label="Кол-во" value={formatNumber(snapshot.quantity, 0)} />
            <EventMetric label="Цена" value={formatNumber(snapshot.price, 4)} />
            <EventMetric label="YTM" value={formatPctPlain(snapshot.ytm)} />
            <EventMetric label="Duration" value={formatNumber(snapshot.duration, 2)} />
          </div>
        </div>
      ))}
    </div>
  )
}

function EventMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-slate-50 px-2 py-1.5">
      <div className="text-[10px] font-bold uppercase text-slate-400">{label}</div>
      <div className="mt-0.5 truncate font-bold text-slate-800">{value}</div>
    </div>
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
  start_date: string
  frequency: string
  base: string
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
    start_date: '',
    frequency: '',
    base: '30/360',
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
      cdu_id: existing.cdu_id ?? '',
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
      start_date: '',
      frequency: '',
      base: '30/360',
      notes: existing.notes ?? '',
    }
  })

  const save = useMutation({
    mutationFn: async () => {
      const num = (s: string) => (s.trim() === '' ? null : Number(s))
      const payload: Record<string, unknown> = {
        cdu_id: form.cdu_id || null,
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
      if (form.start_date) payload.start_date = form.start_date
      if (form.frequency) payload.frequency = Number(form.frequency)
      if (form.base) payload.base = form.base
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
            {isEdit ? `Редактирование: ${existing!.isin}` : 'Новая запись справочника ЦБ'}
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
              Это портфельная позиция из автосинхронизации. Поля <b>Количество</b> и{' '}
              <b>Средняя цена покупки</b> пересчитываются из Trade-данных и не редактируются здесь.
              Реквизиты финансового инструмента ведутся отдельно в паспорте выпуска.
            </div>
          )}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="ЧДУ (необязательно)">
              <select
                className="input"
                value={form.cdu_id}
                onChange={(e) => set('cdu_id', e.target.value ? Number(e.target.value) : '')}
                disabled={isEdit}
              >
                <option value="">— без ЧДУ (только справочник) —</option>
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
            <Field label="Дата начала обращения">
              <input
                type="date"
                className="input"
                value={form.start_date}
                onChange={(e) => set('start_date', e.target.value)}
              />
            </Field>
            <Field label="Выплат купона в год">
              <select className="input" value={form.frequency} onChange={(e) => set('frequency', e.target.value)}>
                <option value="">— не менять —</option>
                <option value="1">1 (ежегодно)</option>
                <option value="2">2 (раз в полгода)</option>
                <option value="4">4 (ежеквартально)</option>
                <option value="12">12 (ежемесячно)</option>
              </select>
            </Field>
            <Field label="Расчётный базис">
              <select className="input" value={form.base} onChange={(e) => set('base', e.target.value)}>
                {['30/360', 'act/360', 'act/365', 'act/act'].map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
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
            disabled={save.isPending || !form.isin.trim()}
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
  label: string
  required?: boolean
  children: ReactNode
  className?: string
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
