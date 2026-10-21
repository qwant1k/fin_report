import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowDownCircle, Clock, FileSpreadsheet, FileText, Hand, Info, Landmark, Loader2 } from 'lucide-react'
import clsx from 'clsx'

import { api } from '@/lib/api'
import { formatDate, formatNumber, formatPct } from '@/lib/format'
import { useAuthStore } from '@/lib/auth'
import OperationWizard from '@/components/OperationWizard'
import { operationLabel } from '@/lib/displayLabels'
import FormulaExplainer, { type FormulaExplanation } from '@/components/FormulaExplainer'

// ───────────────────────── types of /dashboard/category-breakdown ─────────────────────────

export interface SourceInfo {
  kind: string
  label: string
  doc_id?: number | null
  file_name?: string | null
  doc_date?: string | null
  uploaded_at?: string | null
  trade_id?: number | null
  deal_id?: string | null
  status?: string | null
  status_label?: string | null
}

interface BondItem {
  code: string; isin: string; name: string | null; issuer: string | null; currency: string
  quantity: number | null; unit_nominal: number | null; face_value: number
  purchase_price: number | null; price: number | null; price_source: string | null
  price_source_label: string | null; price_date: string | null
  accrued: number; clean_value: number; total_value: number; fx_rate: number; value_kzt: number
  ytm: number | null; duration: number | null
  trade_date: string | null; settlement_date: string | null; maturity_date: string | null
  coupon_rate_pct: number | null; origin_label: string; source: SourceInfo; warnings: string[]
}

interface MMItem {
  code: string | null; deal_id: string | null; collateral: string | null; quantity: number | null
  isin?: string | null; collateral_ticker?: string | null
  open_date: string | null; close_date: string | null; days_total: number | null; days_passed: number | null
  open_amount: number; close_amount: number | null; rate: number | null; base: number
  accrued: number; value_kzt: number; ytm: number | null; duration: number | null
  origin_label: string; source: SourceInfo; warnings: string[]
}

interface Movement {
  id: number; date: string; type_label: string; purpose: string | null; comment: string | null
  account: string | null; amount: number; currency: string; amount_kzt: number
  related_isin: string | null; is_manual: boolean; counted: boolean; source: SourceInfo
}

interface CashData {
  opening: { date: string | null; total: number; label: string
    lines: Array<{ currency: string; amount: number; amount_kzt: number; account: string | null; source: SourceInfo }> }
  movements: Movement[]
  implied: Array<{ date: string; label: string; reference: string; amount_kzt: number; counted: boolean; note: string }>
  pending: Movement[]
  total: number
}

interface Receivable {
  id: number; record_date: string; due_date: string | null; counterparty: string | null
  description: string | null; isin: string | null; currency: string; initial_kzt: number; balance_kzt: number
  status: string; counted: boolean; source: SourceInfo
  transactions: Array<{ id: number; date: string; type_label: string; amount_kzt: number; basis: string; counted: boolean; status_label: string }>
}

interface PendingTrade {
  id: number; date: string; value_date: string | null; operation_type: string; code: string | null
  amount_kzt: number | null; face_value: number | null; comment: string | null; source: SourceInfo
}

interface Breakdown {
  cdu_name: string | null; category: string; label: string; as_of: string; base_date: string | null
  summary_value: number | null; total: number
  kind: 'bonds' | 'money_market' | 'cash' | 'receivables'
  items: Array<BondItem | MMItem | Receivable>
  pending: Array<PendingTrade | Movement | Receivable>
  cash?: CashData
  notes: string[]
}

// ───────────────────────── helpers ─────────────────────────

const SOURCE_STYLE: Record<string, string> = {
  manual: 'bg-violet-50 text-violet-800 ring-violet-600/25',
  trade_report: 'bg-emerald-50 text-emerald-800 ring-emerald-600/25',
  risk_report_xlsm: 'bg-sky-50 text-sky-800 ring-sky-600/25',
  nbrk_daily: 'bg-amber-50 text-amber-800 ring-amber-600/25',
  statement_pdf: 'bg-rose-50 text-rose-800 ring-rose-600/25',
}

export function SourceChip({ source }: { source: SourceInfo }) {
  const Icon = source.kind === 'manual' ? Hand : source.kind === 'nbrk_daily' ? Landmark
    : source.kind === 'statement_pdf' ? FileText : FileSpreadsheet
  const title = [
    source.label,
    source.file_name && `Файл: ${source.file_name}`,
    source.deal_id && `Сделка: ${source.deal_id}`,
    source.uploaded_at && `Загружен: ${formatDate(source.uploaded_at)}`,
    source.status_label && `Статус: ${source.status_label}`,
  ].filter(Boolean).join('\n')
  return (
    <span title={title} className={clsx(
      'inline-flex max-w-[16rem] items-start gap-1 rounded-md px-1.5 py-0.5 text-[11px] leading-tight ring-1 ring-inset',
      SOURCE_STYLE[source.kind] ?? 'bg-slate-100 text-slate-700 ring-slate-500/20',
    )}>
      <Icon className="mt-px h-3 w-3 shrink-0" />
      <span className="min-w-0">
        <span className="block truncate font-semibold">{source.label}</span>
        {source.file_name && <span className="block truncate opacity-80">{source.file_name}</span>}
        {!source.file_name && source.status_label && source.status_label !== 'согласовано' && (
          <span className="block truncate opacity-80">{source.status_label}</span>
        )}
      </span>
    </span>
  )
}

function Money({ v, digits = 2, signed = false }: { v: number | null | undefined; digits?: number; signed?: boolean }) {
  if (v == null) return <span className="text-slate-400">—</span>
  return (
    <span className={clsx(signed && v > 0 && 'text-emerald-700', signed && v < 0 && 'text-red-700')}>
      {signed && v > 0 ? '+' : ''}{formatNumber(v, digits)}
    </span>
  )
}

function Warn({ items }: { items: string[] }) {
  if (!items.length) return null
  return (
    <span title={items.join('\n')} className="ml-1 inline-flex text-amber-600">
      <AlertTriangle className="h-3.5 w-3.5" />
    </span>
  )
}

function pricePriority(item: BondItem) {
  const source = (item.price_source ?? '').toLowerCase()
  const market = source === 'market' || source.includes('kase')
  const risk = source.includes('risk')
  return {
    selected: item.price_source_label ?? (market ? 'KASE' : risk ? 'Параметры риска' : 'Номинал'),
    steps: [
      { label: '1. Рыночная цена KASE', active: market, note: market ? `Цена ${formatNumber(item.price, 4)} от ${formatDate(item.price_date)}` : 'Нет подходящей котировки на дату' },
      { label: '2. Цена из параметров риска', active: risk, note: risk ? `Цена ${formatNumber(item.price, 4)}` : 'Используется, если KASE недоступна' },
      { label: '3. Номинальная стоимость', active: !market && !risk, note: 'Резервный источник при отсутствии рыночных данных' },
    ],
  }
}

function bondAccruedExplanation(item: BondItem): FormulaExplanation {
  const rate = Math.abs(item.coupon_rate_pct ?? 0) > 1 ? (item.coupon_rate_pct ?? 0) / 100 : (item.coupon_rate_pct ?? 0)
  const periodShare = item.face_value && rate ? item.accrued / (item.face_value * rate) : 0
  return {
    title: 'Накопленный купонный доход',
    instrument: item.code || item.isin,
    formula: 'НКД = Номинал × Купонная ставка × Доля купонного периода',
    substituted: `${formatNumber(item.face_value, 2)} × ${formatPct(rate)} × ${formatNumber(periodShare, 6)} = ${formatNumber(item.accrued, 2)} ₸`,
    result: `${formatNumber(item.accrued, 2)} ₸`,
    inputs: [
      { label: 'Номинал позиции', value: `${formatNumber(item.face_value, 2)} ${item.currency}` },
      { label: 'Купонная ставка', value: formatPct(rate) },
      { label: 'Доля купонного периода', value: formatNumber(periodShare, 6) },
      { label: 'Дата расчётов', value: formatDate(item.settlement_date) || '—' },
    ],
    priceSource: pricePriority(item),
    note: 'Доля периода рассчитывается по купонному графику и базе дней инструмента.',
  }
}

function bondDurationExplanation(item: BondItem): FormulaExplanation {
  const couponRate = Math.abs(item.coupon_rate_pct ?? 0) > 1 ? (item.coupon_rate_pct ?? 0) / 100 : (item.coupon_rate_pct ?? 0)
  return {
    title: 'Модифицированная дюрация',
    instrument: item.code || item.isin,
    formula: 'Dmod = [Σ(t × PV(CFₜ)) / ΣPV(CFₜ)] ÷ (1 + YTM / f)',
    substituted: `DURATION(${formatDate(item.settlement_date)}, ${formatDate(item.maturity_date)}, ${formatPct(couponRate)}, ${formatPct(item.ytm ?? 0)}) = ${formatNumber(item.duration, 4)}`,
    result: `${formatNumber(item.duration, 4)} года`,
    inputs: [
      { label: 'Дата оценки', value: formatDate(item.settlement_date) || '—' },
      { label: 'Дата погашения', value: formatDate(item.maturity_date) || '—' },
      { label: 'YTM', value: item.ytm != null ? formatPct(item.ytm) : '—' },
      { label: 'Купон', value: item.coupon_rate_pct != null ? formatPct(couponRate) : '—' },
      { label: 'Рыночная цена', value: item.price != null ? formatNumber(item.price, 4) : '—' },
    ],
    priceSource: pricePriority(item),
    note: 'Расчёт повторяет методику Excel MDURATION; денежные потоки строятся по купонному графику.',
  }
}

function repoExplanation(item: MMItem, metric: 'accrued' | 'value'): FormulaExplanation {
  const rate = Math.abs(item.rate ?? 0) > 1 ? (item.rate ?? 0) / 100 : (item.rate ?? 0)
  const accruedFormula = item.close_amount != null && item.days_total
    ? `(${formatNumber(item.close_amount, 2)} − ${formatNumber(item.open_amount, 2)}) × ${item.days_passed ?? 0} / ${item.days_total}`
    : `${formatNumber(item.open_amount, 2)} × ${formatPct(rate)} × ${item.days_passed ?? 0} / ${item.base || 365}`
  const title = metric === 'value' ? 'Стоимость РЕПО на дату' : 'Начисленное вознаграждение РЕПО'
  return {
    title,
    instrument: item.deal_id || item.code || item.isin || 'РЕПО',
    formula: metric === 'value' ? 'Стоимость = Сумма открытия + Начисленное вознаграждение' : 'Вознаграждение начисляется линейно за прошедшие дни',
    substituted: metric === 'value'
      ? `${formatNumber(item.open_amount, 2)} + ${formatNumber(item.accrued, 2)} = ${formatNumber(item.value_kzt, 2)} ₸`
      : `${accruedFormula} = ${formatNumber(item.accrued, 2)} ₸`,
    result: `${formatNumber(metric === 'value' ? item.value_kzt : item.accrued, 2)} ₸`,
    inputs: [
      { label: 'Сумма открытия', value: `${formatNumber(item.open_amount, 2)} ₸` },
      { label: 'Сумма закрытия', value: item.close_amount != null ? `${formatNumber(item.close_amount, 2)} ₸` : '—' },
      { label: 'Ставка', value: item.rate != null ? formatPct(rate) : '—' },
      { label: 'Прошло / всего дней', value: `${item.days_passed ?? '—'} / ${item.days_total ?? '—'}` },
      { label: 'База дней', value: String(item.base || 365) },
    ],
    note: item.close_amount != null ? 'Приоритет имеет сумма закрытия из условий сделки.' : 'Если сумма закрытия не задана, применяется ставка РЕПО.',
  }
}

// ───────────────────────── main ─────────────────────────

export default function CategoryBreakdown({ cduId, category, date }: { cduId: number; category: string; date: string }) {
  const q = useQuery<Breakdown>({
    queryKey: ['category-breakdown', cduId, category, date],
    queryFn: async () => (await api.get('/dashboard/category-breakdown', { params: { cdu_id: cduId, category, date } })).data,
  })

  if (q.isLoading) {
    return <div className="flex items-center gap-2 p-4 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Загрузка расшифровки…</div>
  }
  if (q.isError || !q.data) {
    return <div className="p-4 text-sm text-red-600">Не удалось загрузить расшифровку</div>
  }
  const d = q.data
  const diff = d.summary_value != null ? d.total - d.summary_value : 0

  return (
    <div className="space-y-3 p-3 sm:p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <div className="text-sm font-semibold text-slate-900">{d.label} — расшифровка</div>
          <div className="text-xs text-slate-600">
            {d.cdu_name} · на {formatDate(d.as_of)}
            {d.base_date && <> · база: срез отчёта о рисках от {formatDate(d.base_date)}</>}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs text-slate-500">Итого по расшифровке</div>
          <div className="text-base font-bold tabular-nums text-slate-900">{formatNumber(d.total, 2)} ₸</div>
          {Math.abs(diff) > 1 && (
            <div className="text-xs text-amber-700">в сводке: {formatNumber(d.summary_value, 2)} — нужен пересчёт</div>
          )}
        </div>
      </div>

      {d.kind === 'bonds' && <BondsTable items={d.items as BondItem[]} total={d.total} />}
      {d.kind === 'money_market' && <MoneyMarketTable items={d.items as MMItem[]} total={d.total} repo={d.category === 'REVERSE_REPO'} />}
      {d.kind === 'cash' && d.cash && <CashView cash={d.cash} />}
      {d.kind === 'receivables' && <ReceivablesTable items={d.items as Receivable[]} total={d.total} cduId={cduId} date={date} />}

      {d.kind !== 'cash' && d.pending.length > 0 && <PendingBlock rows={d.pending} kind={d.kind} />}

      {d.notes.length > 0 && (
        <ul className="space-y-0.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
          {d.notes.map((n) => (
            <li key={n} className="flex gap-1.5"><Info className="mt-0.5 h-3 w-3 shrink-0 text-slate-400" />{n}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Empty({ cols, text = 'Нет позиций на дату' }: { cols: number; text?: string }) {
  return <tr><td colSpan={cols} className="py-5 text-center text-slate-400">{text}</td></tr>
}

function BondsTable({ items, total }: { items: BondItem[]; total: number }) {
  const [explanation, setExplanation] = useState<FormulaExplanation | null>(null)
  return (
    <><div className="overflow-x-auto rounded-lg border border-slate-300 bg-white">
      <table className="detail-table">
        <thead>
          <tr>
            <th>Бумага</th>
            <th>ISIN</th>
            <th className="num">Кол-во, шт</th>
            <th className="num">Номинал</th>
            <th className="num">Цена, %</th>
            <th>Источник цены</th>
            <th className="num">НКД</th>
            <th className="num">Стоимость, ₸</th>
            <th className="num">YTM</th>
            <th className="num">Dur</th>
            <th>Покупка / расчёты</th>
            <th>Погашение</th>
            <th>Откуда позиция</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={`${it.isin}-${i}`}>
              <td>
                <div className="font-mono text-xs font-semibold">{it.code}<Warn items={it.warnings} /></div>
                {it.name && <div className="text-[11px] text-slate-500">{it.name}</div>}
              </td>
              <td className="whitespace-nowrap font-mono text-xs">{it.isin || '—'}</td>
              <td className="num">{it.quantity != null ? formatNumber(it.quantity, 0) : '—'}</td>
              <td className="num">{formatNumber(it.face_value, 0)}{it.currency !== 'KZT' && <span className="text-slate-500"> {it.currency}</span>}</td>
              <td className="num">{it.price != null ? formatNumber(it.price, 4) : '—'}</td>
              <td className="text-xs">
                <div>{it.price_source_label ?? '—'}</div>
                {it.price_date && <div className="text-[11px] text-slate-500">от {formatDate(it.price_date)}</div>}
              </td>
              <td className="num"><button type="button" className="rounded px-1 font-mono text-indigo-700 underline decoration-dotted underline-offset-2 hover:bg-indigo-50" onClick={() => setExplanation(bondAccruedExplanation(it))} title="Показать расчёт НКД">{formatNumber(it.accrued, 2)}</button></td>
              <td className="num font-semibold">{formatNumber(it.value_kzt, 2)}</td>
              <td className="num">{it.ytm != null ? formatPct(it.ytm) : '—'}</td>
              <td className="num">{it.duration != null ? <button type="button" className="rounded px-1 font-mono text-indigo-700 underline decoration-dotted underline-offset-2 hover:bg-indigo-50" onClick={() => setExplanation(bondDurationExplanation(it))} title="Показать расчёт дюрации">{formatNumber(it.duration, 2)}</button> : '—'}</td>
              <td className="whitespace-nowrap text-xs">{formatDate(it.trade_date)}<div className="text-slate-500">{formatDate(it.settlement_date)}</div></td>
              <td className="whitespace-nowrap text-xs">{formatDate(it.maturity_date)}</td>
              <td><SourceChip source={it.source} /></td>
            </tr>
          ))}
          {!items.length && <Empty cols={13} />}
        </tbody>
        {items.length > 1 && (
          <tfoot><tr><td colSpan={7}>Итого: {items.length} поз.</td><td className="num">{formatNumber(total, 2)}</td><td colSpan={5} /></tr></tfoot>
        )}
      </table>
    </div><FormulaExplainer explanation={explanation} onClose={() => setExplanation(null)} /></>
  )
}

function MoneyMarketTable({ items, total, repo }: { items: MMItem[]; total: number; repo: boolean }) {
  const [explanation, setExplanation] = useState<FormulaExplanation | null>(null)
  return (
    <><div className="overflow-x-auto rounded-lg border border-slate-300 bg-white">
      <table className="detail-table">
        <thead>
          <tr>
            <th>{repo ? 'Сделка / залог' : 'Депозит'}</th>
            {repo && <th>ISIN</th>}
            <th>Открытие</th>
            <th>Закрытие</th>
            <th className="num">Дней (прошло / всего)</th>
            <th className="num">Сумма открытия</th>
            <th className="num">Сумма закрытия</th>
            <th className="num">Ставка</th>
            <th className="num">Начислено</th>
            <th className="num">Стоимость, ₸</th>
            <th>Источник</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={`${it.deal_id}-${i}`}>
              <td>
                <div className="font-mono text-xs font-semibold">{it.deal_id || it.code || '—'}<Warn items={it.warnings} /></div>
                {repo && (it.collateral || it.quantity) && (
                  <div className="text-[11px] text-slate-500">
                    залог {it.collateral_ticker ?? it.collateral ?? '—'}{it.quantity ? ` · ${formatNumber(it.quantity, 0)} шт` : ''}
                  </div>
                )}
              </td>
              {repo && <td className="whitespace-nowrap font-mono text-xs">{it.isin || '—'}</td>}
              <td className="whitespace-nowrap">{formatDate(it.open_date)}</td>
              <td className="whitespace-nowrap">{formatDate(it.close_date)}</td>
              <td className="num">{it.days_passed ?? '—'} / {it.days_total ?? '—'}</td>
              <td className="num">{formatNumber(it.open_amount, 2)}</td>
              <td className="num">{it.close_amount != null ? formatNumber(it.close_amount, 2) : '—'}</td>
              <td className="num">{it.rate != null ? formatPct(it.rate) : '—'}</td>
              <td className="num">{repo ? <button type="button" className="rounded px-1 font-mono text-indigo-700 underline decoration-dotted underline-offset-2 hover:bg-indigo-50" onClick={() => setExplanation(repoExplanation(it, 'accrued'))}>{formatNumber(it.accrued, 2)}</button> : formatNumber(it.accrued, 2)}</td>
              <td className="num font-semibold">{repo ? <button type="button" className="rounded px-1 font-mono text-indigo-700 underline decoration-dotted underline-offset-2 hover:bg-indigo-50" onClick={() => setExplanation(repoExplanation(it, 'value'))}>{formatNumber(it.value_kzt, 2)}</button> : formatNumber(it.value_kzt, 2)}</td>
              <td><SourceChip source={it.source} /></td>
            </tr>
          ))}
          {!items.length && <Empty cols={repo ? 11 : 10} />}
        </tbody>
        {items.length > 1 && (
          <tfoot><tr><td colSpan={repo ? 9 : 8}>Итого: {items.length} сделок</td><td className="num">{formatNumber(total, 2)}</td><td /></tr></tfoot>
        )}
      </table>
    </div><FormulaExplainer explanation={explanation} onClose={() => setExplanation(null)} /></>
  )
}

function MovementRows({ rows, muted = false }: { rows: Movement[]; muted?: boolean }) {
  return (
    <>
      {rows.map((m) => (
        <tr key={m.id} className={clsx(muted && 'opacity-70')}>
          <td className="whitespace-nowrap">{formatDate(m.date)}</td>
          <td>{m.type_label}</td>
          <td className="max-w-[22rem]">
            <div className="truncate" title={m.purpose ?? ''}>{m.purpose || '—'}</div>
            {(m.comment || m.related_isin) && (
              <div className="truncate text-[11px] text-slate-500">{[m.related_isin, m.comment].filter(Boolean).join(' · ')}</div>
            )}
          </td>
          <td className="font-mono text-[11px]">{m.account || '—'}</td>
          <td className="num font-semibold"><Money v={m.amount_kzt} signed /></td>
          <td><SourceChip source={m.source} /></td>
        </tr>
      ))}
    </>
  )
}

function CashView({ cash }: { cash: CashData }) {
  const counted = cash.implied.filter((i) => i.counted)
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-slate-300 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-slate-100 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-slate-600">
          <span>Входящий остаток — {cash.opening.label}</span>
          <span className="tabular-nums text-slate-900">{formatNumber(cash.opening.total, 2)} ₸</span>
        </div>
        {cash.opening.lines.length > 0 ? (
          <div className="flex flex-wrap gap-2 p-2">
            {cash.opening.lines.map((l, i) => (
              <div key={i} className="rounded-md border border-slate-200 px-2 py-1 text-xs">
                <span className="font-semibold">{formatNumber(l.amount, 2)} {l.currency}</span>
                {l.currency !== 'KZT' && <span className="text-slate-500"> = {formatNumber(l.amount_kzt, 2)} ₸</span>}
                {l.account && <span className="ml-1 font-mono text-slate-500">{l.account}</span>}
                <span className="ml-1.5"><SourceChip source={l.source} /></span>
              </div>
            ))}
          </div>
        ) : (
          <div className="px-3 py-2 text-xs text-slate-500">Среза денег нет — остаток считается только из движений</div>
        )}
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-300 bg-white">
        <table className="detail-table">
          <thead>
            <tr>
              <th>Дата</th><th>Вид</th><th>Назначение</th><th>Счёт</th><th className="num">Сумма, ₸</th><th>Источник</th>
            </tr>
          </thead>
          <tbody>
            <MovementRows rows={cash.movements} />
            {counted.map((f) => (
              <tr key={`${f.reference}-${f.date}`}>
                <td>{formatDate(f.date)}</td><td>{f.label}</td>
                <td className="text-xs">{f.reference} — {f.note}</td><td>—</td>
                <td className="num font-semibold"><Money v={f.amount_kzt} signed /></td>
                <td><SourceChip source={{ kind: 'risk_report_xlsm', label: 'По данным отчёта о рисках' }} /></td>
              </tr>
            ))}
            {!cash.movements.length && !counted.length && <Empty cols={6} text="Движений после входящего остатка нет" />}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={4}>Остаток = {formatNumber(cash.opening.total, 2)} + движения</td>
              <td className="num">{formatNumber(cash.total, 2)}</td><td />
            </tr>
          </tfoot>
        </table>
      </div>

      {cash.pending.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-amber-300 bg-amber-50/40">
          <div className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-amber-800">
            <Clock className="h-3.5 w-3.5" /> Не учтено — ждёт согласования вторым пользователем
            <Link to="/accounting" className="ml-auto font-medium underline">Открыть очередь</Link>
          </div>
          <table className="detail-table"><tbody><MovementRows rows={cash.pending} muted /></tbody></table>
        </div>
      )}
    </div>
  )
}

function ReceivablesTable({ items, total, cduId, date }: { items: Receivable[]; total: number; cduId: number; date: string }) {
  const can = useAuthStore((s) => s.can)
  const canBook = can('manual.receivables.manage') || can('manual.cash.manage')
  const [receive, setReceive] = useState<Receivable | null>(null)
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-300 bg-white">
      <OperationWizard
        open={receive !== null}
        onClose={() => setReceive(null)}
        defaultCduId={cduId}
        initialPurpose="RECEIVABLE_CLOSE"
        initialForm={receive ? {
          cdu_id: String(cduId),
          receivable_id: String(receive.id),
          amount: String(Math.round(receive.balance_kzt * 100) / 100),
          operation_date: receive.due_date && receive.due_date <= date ? receive.due_date : date,
          purpose_text: receive.description ?? '',
        } : undefined}
      />
      <table className="detail-table">
        <thead>
          <tr>
            <th>Дата</th><th>Контрагент / основание</th><th className="num">Первоначально</th>
            <th>Погашения и корректировки</th><th className="num">Остаток, ₸</th><th>Срок</th><th>Источник</th>
            {canBook && <th />}
          </tr>
        </thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <td className="whitespace-nowrap">{formatDate(r.record_date)}</td>
              <td>
                <div className="font-semibold">{r.counterparty || '—'}</div>
                <div className="text-[11px] text-slate-500">{[r.isin, r.description].filter(Boolean).join(' · ')}</div>
              </td>
              <td className="num">{formatNumber(r.initial_kzt, 2)}</td>
              <td className="text-xs">
                {r.transactions.length ? r.transactions.map((t) => (
                  <div key={t.id} className={clsx(!t.counted && 'text-slate-400')}>
                    {formatDate(t.date)} · {t.type_label} <Money v={t.amount_kzt} signed />
                    {!t.counted && ` (${t.status_label})`}
                  </div>
                )) : <span className="text-slate-400">—</span>}
              </td>
              <td className="num font-semibold">{formatNumber(r.balance_kzt, 2)}</td>
              <td className="whitespace-nowrap">{formatDate(r.due_date)}</td>
              <td><SourceChip source={r.source} /></td>
              {canBook && (
                <td className="whitespace-nowrap">
                  {r.balance_kzt > 0.005 && (
                    <button type="button" className="inline-flex items-center gap-1 rounded-md border border-emerald-300 bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-800 hover:bg-emerald-100"
                      title="Указать дату фактического поступления: деньги придут на счёт, задолженность закроется"
                      onClick={() => setReceive(r)}>
                      <ArrowDownCircle className="h-3.5 w-3.5" /> Поступление
                    </button>
                  )}
                </td>
              )}
            </tr>
          ))}
          {!items.length && <Empty cols={canBook ? 8 : 7} text="Дебиторской задолженности на дату нет" />}
        </tbody>
        {items.length > 1 && (
          <tfoot><tr><td colSpan={4}>Итого</td><td className="num">{formatNumber(total, 2)}</td><td colSpan={canBook ? 3 : 2} /></tr></tfoot>
        )}
      </table>
    </div>
  )
}

function PendingBlock({ rows, kind }: { rows: Array<PendingTrade | Movement | Receivable>; kind: string }) {
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50/40 px-3 py-2 text-xs text-amber-900">
      <div className="mb-1 flex items-center gap-1.5 font-semibold">
        <Clock className="h-3.5 w-3.5" /> Не учтено — ждёт согласования ({rows.length})
        <Link to="/accounting" className="ml-auto font-medium underline">Открыть очередь</Link>
      </div>
      {rows.map((r) => {
        if (kind === 'receivables') {
          const x = r as Receivable
          return <div key={x.id}>{formatDate(x.record_date)} · {x.counterparty} · {formatNumber(x.initial_kzt, 2)} ₸</div>
        }
        const t = r as PendingTrade
        return (
          <div key={t.id}>
            {formatDate(t.date)} · {operationLabel(t.operation_type)} {t.code ?? ''} · {formatNumber(t.amount_kzt, 2)} ₸ · <SourceChip source={t.source} />
          </div>
        )
      })}
    </div>
  )
}
