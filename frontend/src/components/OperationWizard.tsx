import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowDownCircle, ArrowUpCircle, BadgePercent, Banknote, Coins, FileMinus2, FilePlus2, HandCoins,
  Info, Landmark, PiggyBank, Receipt, Scale, ShoppingCart, Undo2, Wallet, type LucideIcon,
} from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'

import { api } from '@/lib/api'
import { apiErrorMessage, notificationText } from '@/lib/notifications'
import { formatNumber } from '@/lib/format'
import { useWorkContextStore } from '@/lib/workContext'
import { Modal } from '@/components/ui'
import type { CDU } from '@/lib/types'

interface Purpose {
  code: string
  label: string
  group: string
  kind: 'cash' | 'trade' | 'receivable_close' | 'receivable_open'
  sign: number
  hint: string
}

const ICON: Record<string, LucideIcon> = {
  CASH_RECEIPT: ArrowDownCircle,
  CONTRIBUTION: PiggyBank,
  COUPON: BadgePercent,
  OPENING_BALANCE: Wallet,
  CASH_PAYMENT: ArrowUpCircle,
  WITHDRAWAL: Undo2,
  COMMISSION: Receipt,
  SECURITY_BUY: ShoppingCart,
  SECURITY_SELL: HandCoins,
  REDEMPTION: Landmark,
  RECEIVABLE_CLOSE: FileMinus2,
  RECEIVABLE_OPEN: FilePlus2,
  CORRECTION: Scale,
  OTHER: Coins,
}

interface OpenReceivable {
  id: number
  counterparty: string | null
  description: string | null
  record_date: string
  due_date: string | null
  balance_kzt: number
}

interface RefRow { isin: string; ticker_kase: string | null; instrument_name: string | null; nominal: number | null }

function parseAmount(v: string): number | null {
  const s = v.replace(/\s/g, '').replace(',', '.')
  if (!s) return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}

/**
 * «Новая операция»: one form for any manual operation — the user only picks
 * the purpose (поступление денег, покупка ЦБ, закрытие дебиторки, …).
 * Required are the date and the amount; everything else is optional.
 */
export default function OperationWizard({
  open, onClose, defaultCduId, initialPurpose, initialForm,
}: {
  open: boolean; onClose: () => void; defaultCduId?: number | null
  /** preselected purpose and field values, e.g. «Закрытие дебиторки» from the receivables list */
  initialPurpose?: string; initialForm?: Record<string, string>
}) {
  const qc = useQueryClient()
  const workDate = useWorkContextStore((s) => s.workDate)
  const [purpose, setPurpose] = useState<string>('CASH_RECEIPT')
  const [form, setForm] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  const meta = useQuery<{ purposes: Purpose[]; default_portfolio: { id: number; name: string } | null }>({
    queryKey: ['operation-purposes'],
    queryFn: async () => (await api.get('/accounting/operation-purposes')).data,
    enabled: open,
    staleTime: 3600_000,
  })
  const cdus = useQuery<CDU[]>({ queryKey: ['cdus'], queryFn: async () => (await api.get('/settings/cdus')).data, enabled: open })
  const current = meta.data?.purposes.find((p) => p.code === purpose)
  const kind = current?.kind ?? 'cash'
  const cduId = form.cdu_id ?? (defaultCduId ? String(defaultCduId) : '')

  const accounts = useQuery<Array<{ account: string; currency?: string }>>({
    queryKey: ['known-accounts', cduId],
    queryFn: async () => (await api.get('/accounting/accounts', { params: { cdu_id: cduId || undefined } })).data,
    enabled: open && kind === 'cash',
  })
  const receivables = useQuery<OpenReceivable[]>({
    queryKey: ['open-receivables', cduId, form.operation_date ?? workDate],
    queryFn: async () => (await api.get('/accounting/open-receivables', {
      params: { cdu_id: cduId || undefined, as_of: form.operation_date || workDate },
    })).data,
    enabled: open && kind === 'receivable_close',
  })
  const refs = useQuery<RefRow[]>({
    queryKey: ['reference-lite'],
    queryFn: async () => (await api.get('/securities/reference', { params: { limit: 5000 } })).data,
    enabled: open && (kind === 'trade' || purpose === 'COUPON' || kind === 'receivable_open'),
    staleTime: 600_000,
  })

  useEffect(() => {
    if (open) { setForm(initialForm ?? {}); setPurpose(initialPurpose ?? 'CASH_RECEIPT') }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }))
  const groups = useMemo(() => {
    const out: Record<string, Purpose[]> = {}
    for (const p of meta.data?.purposes ?? []) (out[p.group] ??= []).push(p)
    return out
  }, [meta.data])

  // purchase/sale: amount can be calculated from quantity × nominal × price
  const ref = useMemo(() => {
    const key = (form.isin ?? '').trim().toUpperCase()
    return (refs.data ?? []).find((r) => r.isin === key || (r.ticker_kase ?? '').toUpperCase() === key)
  }, [refs.data, form.isin])
  const estimate = useMemo(() => {
    const q = parseAmount(form.quantity ?? '')
    const p = parseAmount(form.price ?? '')
    if (kind !== 'trade' || q == null || p == null || !ref?.nominal) return null
    return q * ref.nominal * p / 100
  }, [kind, form.quantity, form.price, ref])

  const amount = parseAmount(form.amount ?? '')
  const signHint = current?.sign === 1 ? 'увеличит остаток денег' : current?.sign === -1 ? 'уменьшит остаток денег' : 'знак суммы учитывается'

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      const payload: Record<string, unknown> = {
        purpose,
        operation_date: form.operation_date || workDate,
        amount: amount ?? (estimate != null ? estimate : undefined),
        currency: form.currency || 'KZT',
        cdu_id: cduId || undefined,
        purpose_text: form.purpose_text || undefined,
        account: form.account || undefined,
        comment: form.comment || undefined,
        isin: form.isin || undefined,
        quantity: form.quantity || undefined,
        price: form.price || undefined,
        value_date: form.value_date || undefined,
        receivable_id: form.receivable_id || undefined,
        counterparty: form.counterparty || undefined,
        due_date: form.due_date || undefined,
      }
      const r = (await api.post('/accounting/operations', payload)).data
      toast.success(notificationText(r.message, 'Операция сохранена и отправлена на согласование'), { duration: 6000 })
      if (r.portfolio_note) toast(notificationText(r.portfolio_note, 'Состав портфеля обновлён'), { icon: 'ℹ️', duration: 6000 })
      for (const key of ['accounting', 'category-breakdown', 'dashboard', 'workday', 'open-receivables']) {
        qc.invalidateQueries({ queryKey: [key] })
      }
      onClose()
    } catch (err: any) {
      toast.error(apiErrorMessage(err, 'Не удалось сохранить операцию'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={() => { if (!saving) onClose() }}
      size="xl"
      title="Новая операция"
      description="Выберите назначение. Обязательны только дата и сумма — остальные поля можно не заполнять."
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose} disabled={saving}>Отмена</button>
          <button type="submit" form="operation-wizard" className="btn-primary" disabled={saving}>
            {saving ? 'Сохранение…' : 'Сохранить и отправить на согласование'}
          </button>
        </>
      }
    >
      <form id="operation-wizard" onSubmit={submit} className="space-y-4">
        <div className="space-y-2">
          {Object.entries(groups).map(([group, items]) => (
            <div key={group}>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{group}</div>
              <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-4">
                {items.map((p) => {
                  const Icon = ICON[p.code] ?? Banknote
                  const active = p.code === purpose
                  return (
                    <button
                      type="button"
                      key={p.code}
                      onClick={() => setPurpose(p.code)}
                      className={clsx(
                        'flex items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-[13px] font-medium transition',
                        active ? 'border-emerald-600 bg-emerald-50 text-emerald-900 ring-2 ring-emerald-500/20'
                          : 'border-slate-200 bg-white text-slate-700 hover:border-emerald-300 hover:bg-emerald-50/40',
                      )}
                    >
                      <Icon className={clsx('h-4 w-4 shrink-0', active ? 'text-emerald-700' : 'text-slate-500')} />
                      <span className="leading-tight">{p.label}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
          {meta.isLoading && <div className="text-sm text-slate-500">Загрузка…</div>}
        </div>

        {current && (
          <div className="flex items-start gap-2 rounded-lg bg-sky-50 px-3 py-2 text-xs text-sky-900">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{current.hint}{kind !== 'receivable_open' && <> · Операция {signHint}.</>}</span>
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <F label="Дата операции *">
            <input type="date" required className="input" value={form.operation_date ?? workDate}
              onChange={(e) => set('operation_date', e.target.value)} />
          </F>
          <F label={kind === 'trade' ? 'Сумма сделки, ₸ (или кол-во × цена)' : 'Сумма *'}>
            <input inputMode="decimal" className="input text-right font-semibold tabular-nums"
              required={kind !== 'trade'} placeholder={estimate != null ? formatNumber(estimate, 2) : '0,00'}
              value={form.amount ?? ''} onChange={(e) => set('amount', e.target.value)} />
            {amount != null && <span className="mt-0.5 block text-right text-[11px] text-slate-500">{formatNumber(amount, 2)}</span>}
          </F>
          <F label="Валюта">
            <select className="input" value={form.currency ?? 'KZT'} onChange={(e) => set('currency', e.target.value)}>
              {['KZT', 'USD', 'EUR', 'RUB', 'CNY'].map((c) => <option key={c}>{c}</option>)}
            </select>
          </F>
          <F label="ЧДУ / портфель">
            <select className="input" value={cduId} onChange={(e) => set('cdu_id', e.target.value)}>
              <option value="">Не выбран{meta.data?.default_portfolio ? ` → ${meta.data.default_portfolio.name}` : ''}</option>
              {(cdus.data ?? []).filter((c) => c.is_active !== false).map((c) => <option key={c.id} value={c.id}>{c.short_name || c.name}</option>)}
            </select>
          </F>
          <F label="Назначение платежа" wide>
            <input className="input" placeholder={current?.label ?? ''} value={form.purpose_text ?? ''}
              onChange={(e) => set('purpose_text', e.target.value)} />
          </F>

          {kind === 'cash' && (
            <F label="Счёт">
              <input className="input font-mono" list="op-accounts" placeholder="KZ…" value={form.account ?? ''}
                onChange={(e) => set('account', e.target.value)} />
              <datalist id="op-accounts">{(accounts.data ?? []).map((a) => <option key={a.account} value={a.account}>{a.currency}</option>)}</datalist>
            </F>
          )}

          {(kind === 'trade' || purpose === 'COUPON' || kind === 'receivable_open') && (
            <F label={kind === 'trade' ? 'Ценная бумага (ISIN или тикер) *' : 'Ценная бумага (ISIN)'}>
              <input className="input font-mono uppercase" list="op-refs" required={kind === 'trade'} value={form.isin ?? ''}
                onChange={(e) => set('isin', e.target.value)} />
              <datalist id="op-refs">
                {(refs.data ?? []).map((r) => <option key={r.isin} value={r.ticker_kase || r.isin}>{r.isin} {r.instrument_name ?? ''}</option>)}
              </datalist>
              {ref && <span className="mt-0.5 block truncate text-[11px] text-slate-500">{ref.isin} · номинал {formatNumber(ref.nominal, 0)}</span>}
            </F>
          )}

          {kind === 'trade' && (
            <>
              <F label="Количество, шт">
                <input inputMode="decimal" className="input text-right" value={form.quantity ?? ''} onChange={(e) => set('quantity', e.target.value)} />
              </F>
              <F label="Цена, % от номинала">
                <input inputMode="decimal" className="input text-right" value={form.price ?? ''} onChange={(e) => set('price', e.target.value)} />
              </F>
              <F label="Дата расчётов">
                <input type="date" className="input" value={form.value_date ?? ''} onChange={(e) => set('value_date', e.target.value)} />
                <span className="mt-0.5 block text-[11px] text-slate-500">пусто — в дату операции</span>
              </F>
            </>
          )}

          {kind === 'receivable_close' && (
            <F label="Какую задолженность закрыть" wide>
              <select className="input" value={form.receivable_id ?? ''} onChange={(e) => set('receivable_id', e.target.value)}>
                <option value="">Автоматически — открытые по очереди (FIFO)</option>
                {(receivables.data ?? []).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.record_date} · {r.counterparty ?? '—'} · остаток {formatNumber(r.balance_kzt, 2)} ₸
                  </option>
                ))}
              </select>
              {receivables.data && receivables.data.length === 0 && (
                <span className="mt-0.5 block text-[11px] text-amber-700">Открытой дебиторской задолженности у портфеля нет</span>
              )}
            </F>
          )}

          {kind === 'receivable_open' && (
            <>
              <F label="Контрагент / должник">
                <input className="input" value={form.counterparty ?? ''} onChange={(e) => set('counterparty', e.target.value)} />
              </F>
              <F label="Ожидаемая дата погашения">
                <input type="date" className="input" value={form.due_date ?? ''} onChange={(e) => set('due_date', e.target.value)} />
              </F>
            </>
          )}

          <F label="Комментарий" wide>
            <input className="input" value={form.comment ?? ''} onChange={(e) => set('comment', e.target.value)} />
          </F>
        </div>
        <p className="text-xs text-slate-500">
          Операция попадёт в сводку, расшифровки и отчёт после согласования вторым пользователем
          (раздел «Операционный учёт → Согласование»); сводка за дату пересчитается автоматически.
        </p>
      </form>
    </Modal>
  )
}

function F({ label, children, wide }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <label className={clsx('block', wide && 'sm:col-span-2')}>
      <span className="mb-1 block text-xs font-semibold text-slate-600">{label}</span>
      {children}
    </label>
  )
}
