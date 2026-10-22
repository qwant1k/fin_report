import { FormEvent, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BadgeDollarSign, Check, FilePenLine, Plus, ReceiptText, RotateCcw, X } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { formatNumber, formatPct } from '@/lib/format'
import { useAuthStore } from '@/lib/auth'
import { useConfirm } from '@/lib/confirm'
import { Modal, PageHeader } from '@/components/ui'
import type { CDU } from '@/lib/types'
import OperationWizard from '@/components/OperationWizard'
import FormulaExplainer, { type FormulaExplanation } from '@/components/FormulaExplainer'
import { useWorkContextStore } from '@/lib/workContext'
import { apiErrorMessage } from '@/lib/notifications'
import {
  categoryLabel,
  operationLabel,
  receivableStatusLabel,
  workflowStatusLabel,
} from '@/lib/displayLabels'

type Tab = 'trades' | 'repos' | 'cash' | 'receivables' | 'approval'
type EditorKind = 'trade' | 'cash' | 'receivable' | 'receivable-tx'
type Row = Record<string, any>

interface Overview {
  report_date: string
  trades: Row[]
  repo_positions: Row[]
  cash_movements: Row[]
  receivables: Row[]
}

const STATUS: Record<string, { label: string; cls: string }> = {
  APPROVED: { label: 'Согласовано', cls: 'bg-emerald-100 text-emerald-800' },
  PENDING_APPROVAL: { label: 'На согласовании', cls: 'bg-amber-100 text-amber-800' },
  PENDING_CANCELLATION: { label: 'Аннулирование на согласовании', cls: 'bg-orange-100 text-orange-800' },
  REJECTED: { label: 'Отклонено', cls: 'bg-red-100 text-red-800' },
  CANCELLED: { label: 'Аннулировано', cls: 'bg-slate-200 text-slate-700' },
}

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'trades', label: 'Ручные сделки' },
  { id: 'repos', label: 'Действующие РЕПО' },
  { id: 'cash', label: 'Движения денег' },
  { id: 'receivables', label: 'Дебиторка' },
  { id: 'approval', label: 'Согласование' },
]

function today() { return new Date().toISOString().slice(0, 10) }
function value(row: Row | undefined, key: string, fallback: any = '') { return row?.[key] ?? fallback }

function StatusBadge({ value }: { value: string }) {
  const item = STATUS[value] ?? { label: workflowStatusLabel(value), cls: 'bg-slate-100 text-slate-700' }
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${item.cls}`}>{item.label}</span>
}

export default function AccountingPage() {
  const [searchParams] = useSearchParams()
  const qc = useQueryClient()
  const can = useAuthStore((s) => s.can)
  const confirm = useConfirm()
  const reportDate = useWorkContextStore((s) => s.workDate) || today()
  const setReportDate = useWorkContextStore((s) => s.setWorkDate)
  const linkedCdu = Number(searchParams.get('cdu_id')) || ''
  const [cduId, setCduId] = useState<number | ''>(linkedCdu)
  const [tab, setTab] = useState<Tab>(searchParams.get('cdu_id') ? 'receivables' : 'trades')
  const [editor, setEditor] = useState<{ kind: EditorKind; row?: Row; parent?: Row } | null>(null)
  const [wizard, setWizard] = useState(false)
  const canCreate = can('manual.cash.manage') || can('manual.trades.manage') || can('manual.receivables.manage')

  useEffect(() => {
    const linkedDate = searchParams.get('date')
    if (linkedDate && linkedDate !== reportDate) setReportDate(linkedDate)
  }, [reportDate, searchParams, setReportDate])

  const cdus = useQuery<CDU[]>({ queryKey: ['cdus'], queryFn: async () => (await api.get('/settings/cdus')).data })
  const overview = useQuery<Overview>({
    queryKey: ['accounting', reportDate, cduId],
    queryFn: async () => (await api.get('/accounting/overview', { params: { report_date: reportDate, cdu_id: cduId || undefined } })).data,
  })
  const invalidate = () => qc.invalidateQueries({ queryKey: ['accounting'] })

  const decision = useMutation({
    mutationFn: async ({ entity, id, action, comment }: { entity: string; id: number; action: 'approve' | 'reject'; comment?: string }) =>
      (await api.post(`/accounting/${entity}/${id}/${action}`, { comment })).data,
    onSuccess: (r: any, variables) => {
      const action = variables.action === 'approve' ? 'Операция согласована' : 'Операция отклонена'
      toast.success(r?.recalculated_dates?.length
        ? `${action}; сводка пересчитана для ${r.recalculated_dates.length} дат.`
        : `${action}.`)
      invalidate()
      for (const key of ['dashboard', 'workday', 'category-breakdown']) qc.invalidateQueries({ queryKey: [key] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось сохранить решение по операции')),
  })
  const cancel = useMutation({
    mutationFn: async ({ entity, id, comment }: { entity: string; id: number; comment: string }) =>
      (await api.delete(`/accounting/${entity}/${id}`, { data: { comment } })).data,
    onSuccess: () => { toast.success('Запрос на аннулирование отправлен на согласование.'); invalidate() },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось отправить операцию на аннулирование')),
  })

  const pending = useMemo(() => {
    const data = overview.data
    if (!data) return []
    const rows = [
      ...data.trades.map((row) => ({ ...row, entity: 'trades', entityLabel: 'Сделка' })),
      ...data.cash_movements.filter((row) => row.is_manual).map((row) => ({ ...row, entity: 'cash-movements', entityLabel: 'Деньги' })),
      ...data.receivables.flatMap((row) => [
        { ...row, entity: 'receivables', entityLabel: 'Дебиторка' },
        ...(row.transactions ?? []).map((tx: Row) => ({ ...tx, cdu_name: row.cdu_name, entity: 'receivable-transactions', entityLabel: 'Операция по дебиторке' })),
      ]),
    ]
    return rows.filter((row) => ['PENDING_APPROVAL', 'PENDING_CANCELLATION'].includes(row.workflow_status))
  }, [overview.data])

  const askCancel = async (entity: string, id: number) => {
    const { confirmed, comment } = await confirm({
      title: 'Запросить аннулирование операции?',
      description: 'Операция уйдёт на согласование как запрос на аннулирование.',
      tone: 'danger',
      confirmLabel: 'Аннулировать',
      requireComment: 'Причина аннулирования',
    })
    if (confirmed && comment) cancel.mutate({ entity, id, comment })
  }
  const reject = async (entity: string, id: number) => {
    const { confirmed, comment } = await confirm({
      title: 'Отклонить операцию?',
      description: 'Инициатор увидит причину отклонения и сможет исправить операцию.',
      tone: 'danger',
      confirmLabel: 'Отклонить',
      requireComment: 'Причина отклонения',
    })
    if (confirmed && comment) decision.mutate({ entity, id, action: 'reject', comment })
  }
  const approve = async (entity: string, id: number) => {
    const { confirmed } = await confirm({
      title: 'Согласовать операцию?',
      description: 'Операция будет отмечена согласованной и попадёт в расчёт портфеля.',
      confirmLabel: 'Согласовать',
    })
    if (confirmed) decision.mutate({ entity, id, action: 'approve' })
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Операционный учёт"
        subtitle="Ручные операции, денежные движения, РЕПО и дебиторская задолженность с согласованием"
        icon={ReceiptText}
        actions={
          <>
            <select className="input h-10 w-56" value={cduId} onChange={(e) => setCduId(e.target.value ? Number(e.target.value) : '')}>
              <option value="">Все портфели</option>
              {cdus.data?.map((cdu) => <option key={cdu.id} value={cdu.id}>{cdu.short_name}</option>)}
            </select>
            {canCreate && (
              <button className="btn-primary h-10" onClick={() => setWizard(true)}>
                <Plus className="h-4 w-4" /> Новая операция
              </button>
            )}
          </>
        }
      />

      <div className="card overflow-hidden">
        <div className="flex flex-wrap gap-1 border-b border-slate-200 bg-slate-50 p-2">
          {TABS.map((item) => (
            <button key={item.id} className={`rounded-lg px-3 py-2 text-sm font-semibold ${tab === item.id ? 'bg-white text-emerald-700 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`} onClick={() => setTab(item.id)}>
              {item.label}{item.id === 'approval' && pending.length > 0 ? ` (${pending.length})` : ''}
            </button>
          ))}
        </div>

        {overview.isLoading && <div className="p-10 text-center text-slate-500">Загрузка…</div>}
        {overview.isError && <div className="p-10 text-center text-red-600">Не удалось загрузить операционный журнал</div>}
        {overview.data && tab === 'trades' && (
          <TradeTable rows={overview.data.trades} canEdit={can('manual.trades.manage')} onAdd={() => setEditor({ kind: 'trade' })} onEdit={(row) => setEditor({ kind: 'trade', row })} onCancel={(id) => askCancel('trades', id)} />
        )}
        {overview.data && tab === 'repos' && <RepoTable rows={overview.data.repo_positions} />}
        {overview.data && tab === 'cash' && (
          <CashTable rows={overview.data.cash_movements} canEdit={can('manual.cash.manage')} onAdd={() => setEditor({ kind: 'cash' })} onEdit={(row) => setEditor({ kind: 'cash', row })} onCancel={(id) => askCancel('cash-movements', id)} />
        )}
        {overview.data && tab === 'receivables' && (
          <ReceivableTable rows={overview.data.receivables} canEdit={can('manual.receivables.manage')} onAdd={() => setEditor({ kind: 'receivable' })} onEdit={(row) => setEditor({ kind: 'receivable', row })} onTx={(row) => setEditor({ kind: 'receivable-tx', parent: row })} onCancel={(id) => askCancel('receivables', id)} />
        )}
        {overview.data && tab === 'approval' && (
          <ApprovalTable rows={pending} canApprove={can('manual.operations.approve')} onApprove={approve} onReject={reject} />
        )}
      </div>

      <OperationWizard open={wizard} onClose={() => { setWizard(false); invalidate() }} defaultCduId={cduId || null} />
      <OperationEditor open={!!editor} editor={editor} reportDate={reportDate} cdus={cdus.data ?? []} onClose={() => setEditor(null)} onSaved={() => { setEditor(null); invalidate() }} />
    </div>
  )
}

function Toolbar({ title, canAdd, onAdd }: { title: string; canAdd: boolean; onAdd: () => void }) {
  return <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3"><h2 className="font-semibold text-slate-900">{title}</h2>{canAdd && <button className="btn-primary" onClick={onAdd}><Plus className="h-4 w-4" />Добавить</button>}</div>
}

function RowActions({ row, canEdit, onEdit, onCancel }: { row: Row; canEdit: boolean; onEdit: () => void; onCancel: () => void }) {
  if (!canEdit || ['CANCELLED', 'PENDING_CANCELLATION'].includes(row.workflow_status)) return null
  return <div className="flex justify-end gap-1"><button className="btn-secondary px-2 py-1" onClick={onEdit}><FilePenLine className="h-4 w-4" /></button><button className="btn-secondary px-2 py-1 text-red-600" onClick={onCancel}><X className="h-4 w-4" /></button></div>
}

function TradeTable({ rows, canEdit, onAdd, onEdit, onCancel }: { rows: Row[]; canEdit: boolean; onAdd: () => void; onEdit: (r: Row) => void; onCancel: (id: number) => void }) {
  return <><Toolbar title="Ручные сделки" canAdd={canEdit} onAdd={onAdd} /><div className="table-wrap"><table className="kdif-table"><thead><tr><th>Дата / расчёты</th><th>ЧДУ</th><th>Операция</th><th>Инструмент</th><th className="text-right">Сумма, ₸</th><th>Статус</th><th>Основание</th><th /></tr></thead><tbody>{rows.map((r) => <tr key={r.id}><td>{r.trade_date}<div className="text-xs text-slate-400">{r.value_date}</div></td><td>{r.cdu_name}</td><td className="font-semibold">{operationLabel(r.operation_type)}</td><td className="font-mono text-xs">{r.isin || r.instrument_code || '—'}</td><td className="text-right font-mono">{formatNumber(r.amount_kzt, 2)}</td><td><StatusBadge value={r.workflow_status} /></td><td className="max-w-64 truncate" title={r.change_reason}>{r.change_reason}</td><td><RowActions row={r} canEdit={canEdit} onEdit={() => onEdit(r)} onCancel={() => onCancel(r.id)} /></td></tr>)}{!rows.length && <tr><td colSpan={8} className="py-10 text-center text-slate-400">Ручных сделок нет</td></tr>}</tbody></table></div></>
}

function repoAccountingExplanation(row: Row, metric: 'accrued' | 'value'): FormulaExplanation {
  const rate = Math.abs(row.repo_rate_pct ?? 0) > 1 ? (row.repo_rate_pct ?? 0) / 100 : (row.repo_rate_pct ?? 0)
  const accrual = row.close_amount && row.term_days
    ? `(${formatNumber(row.close_amount, 2)} − ${formatNumber(row.open_amount, 2)}) × ${row.days_passed ?? 0} / ${row.term_days}`
    : `${formatNumber(row.open_amount, 2)} × ${formatPct(rate)} × ${row.days_passed ?? 0} / ${row.base ?? 365}`
  return {
    title: metric === 'value' ? 'Стоимость РЕПО на дату' : 'Начисленное вознаграждение РЕПО',
    instrument: row.deal_id || row.isin || row.instrument_code || `РЕПО #${row.id}`,
    formula: metric === 'value' ? 'Стоимость = Сумма открытия + Начисленное вознаграждение' : 'Вознаграждение начисляется линейно за прошедшие дни',
    substituted: metric === 'value'
      ? `${formatNumber(row.open_amount, 2)} + ${formatNumber(row.accrued_reward, 2)} = ${formatNumber(row.value_on_date, 2)} ₸`
      : `${accrual} = ${formatNumber(row.accrued_reward, 2)} ₸`,
    result: `${formatNumber(metric === 'value' ? row.value_on_date : row.accrued_reward, 2)} ₸`,
    inputs: [
      { label: 'Сумма открытия', value: `${formatNumber(row.open_amount, 2)} ₸` },
      { label: 'Сумма закрытия', value: row.close_amount ? `${formatNumber(row.close_amount, 2)} ₸` : '—' },
      { label: 'Ставка', value: row.repo_rate_pct == null ? '—' : formatPct(rate) },
      { label: 'Прошло / срок', value: `${row.days_passed ?? '—'} / ${row.term_days ?? '—'} дней` },
      { label: 'База дней', value: String(row.base ?? 365) },
    ],
    note: row.close_amount ? 'Сумма закрытия из условий сделки имеет приоритет перед расчётом по ставке.' : 'Расчёт выполнен по ставке РЕПО.',
  }
}

function RepoTable({ rows }: { rows: Row[] }) {
  const [explanation, setExplanation] = useState<FormulaExplanation | null>(null)
  return <><Toolbar title="РЕПО, действующие на выбранную дату" canAdd={false} onAdd={() => {}} /><div className="table-wrap"><table className="kdif-table"><thead><tr><th>ЧДУ</th><th>Сделка</th><th>Инструмент</th><th>Открытие / закрытие</th><th className="text-right">Сумма открытия</th><th className="text-right">Ставка</th><th className="text-right">Начислено</th><th className="text-right">Стоимость</th></tr></thead><tbody>{rows.map((r) => <tr key={r.id}><td>{r.cdu_name}</td><td className="font-mono text-xs">{r.deal_id || `#${r.id}`}</td><td>{r.isin || r.instrument_code || '—'}</td><td>{r.open_date}<div className="text-xs text-slate-400">до {r.close_date || 'открыто'}</div></td><td className="text-right font-mono">{formatNumber(r.open_amount, 2)}</td><td className="text-right">{r.repo_rate_pct == null ? '—' : formatPct(rateValue(r.repo_rate_pct))}</td><td className="text-right"><button type="button" className="rounded px-1 font-mono text-indigo-700 underline decoration-dotted underline-offset-2 hover:bg-indigo-50" onClick={() => setExplanation(repoAccountingExplanation(r, 'accrued'))}>{formatNumber(r.accrued_reward, 2)}</button></td><td className="text-right font-semibold"><button type="button" className="rounded px-1 font-mono text-indigo-700 underline decoration-dotted underline-offset-2 hover:bg-indigo-50" onClick={() => setExplanation(repoAccountingExplanation(r, 'value'))}>{formatNumber(r.value_on_date, 2)}</button></td></tr>)}{!rows.length && <tr><td colSpan={8} className="py-10 text-center text-slate-400">На выбранную дату действующих операций РЕПО нет</td></tr>}</tbody></table></div><FormulaExplainer explanation={explanation} onClose={() => setExplanation(null)} /></>
}

function rateValue(value: number) { return Math.abs(value) > 1 ? value / 100 : value }

function CashTable({ rows, canEdit, onAdd, onEdit, onCancel }: { rows: Row[]; canEdit: boolean; onAdd: () => void; onEdit: (r: Row) => void; onCancel: (id: number) => void }) {
  return <><Toolbar title="Денежные движения" canAdd={canEdit} onAdd={onAdd} /><div className="table-wrap"><table className="kdif-table"><thead><tr><th>Дата</th><th>ЧДУ</th><th>Счёт</th><th>Вид</th><th className="text-right">Сумма</th><th>Валюта</th><th>Связь</th><th>Статус</th><th>Назначение</th><th /></tr></thead><tbody>{rows.map((r) => <tr key={r.id}><td>{r.operation_date}</td><td>{r.cdu_name}</td><td className="font-mono text-xs">{r.account || '—'}</td><td>{operationLabel(r.movement_type)}</td><td className={`text-right font-mono font-semibold ${r.amount < 0 ? 'text-red-600' : 'text-emerald-700'}`}>{formatNumber(r.amount, 2)}</td><td>{r.currency}</td><td>{r.related_trade_id ? `Сделка #${r.related_trade_id}` : r.related_isin || '—'}</td><td><StatusBadge value={r.workflow_status} /></td><td className="max-w-64 truncate" title={r.basis}>{r.basis}</td><td>{r.is_manual && <RowActions row={r} canEdit={canEdit} onEdit={() => onEdit(r)} onCancel={() => onCancel(r.id)} />}</td></tr>)}{!rows.length && <tr><td colSpan={10} className="py-10 text-center text-slate-400">Движений нет</td></tr>}</tbody></table></div></>
}

function ReceivableTable({ rows, canEdit, onAdd, onEdit, onTx, onCancel }: { rows: Row[]; canEdit: boolean; onAdd: () => void; onEdit: (r: Row) => void; onTx: (r: Row) => void; onCancel: (id: number) => void }) {
  return <><Toolbar title="Дебиторская задолженность" canAdd={canEdit} onAdd={onAdd} /><div className="table-wrap"><table className="kdif-table"><thead><tr><th>Дата</th><th>ЧДУ</th><th>Контрагент / основание</th><th className="text-right">Первоначально</th><th className="text-right">Остаток на дату</th><th>Срок</th><th>Статус</th><th /></tr></thead><tbody>{rows.map((r) => <tr key={r.id}><td>{r.record_date}</td><td>{r.cdu_name}</td><td><div className="font-semibold">{r.counterparty}</div><div className="max-w-72 truncate text-xs text-slate-400">{r.description}</div></td><td className="text-right font-mono">{formatNumber(r.amount_kzt ?? r.amount, 2)} {r.currency}</td><td className="text-right font-mono font-semibold">{formatNumber(r.balance_kzt, 2)}</td><td>{r.due_date || '—'}</td><td><StatusBadge value={r.workflow_status} /><div className="mt-1 text-xs text-slate-400">{receivableStatusLabel(r.status)}</div></td><td><div className="flex justify-end gap-1">{canEdit && r.workflow_status === 'APPROVED' && <button className="btn-secondary px-2 py-1" onClick={() => onTx(r)} title="Погашение / корректировка"><RotateCcw className="h-4 w-4" /></button>}<RowActions row={r} canEdit={canEdit} onEdit={() => onEdit(r)} onCancel={() => onCancel(r.id)} /></div></td></tr>)}{!rows.length && <tr><td colSpan={8} className="py-10 text-center text-slate-400">Дебиторской задолженности нет</td></tr>}</tbody></table></div></>
}

function ApprovalTable({ rows, canApprove, onApprove, onReject }: { rows: Row[]; canApprove: boolean; onApprove: (e: string, id: number) => void; onReject: (e: string, id: number) => void }) {
  return <><Toolbar title="Очередь согласования" canAdd={false} onAdd={() => {}} /><div className="table-wrap"><table className="kdif-table"><thead><tr><th>Тип</th><th>ЧДУ</th><th>Дата</th><th>Создал / изменил</th><th>Статус</th><th>Содержание</th><th className="text-right">Сумма</th><th /></tr></thead><tbody>{rows.map((r) => <tr key={`${r.entity}-${r.id}`}><td>{r.entityLabel}</td><td>{r.cdu_name || '—'}</td><td>{r.trade_date || r.operation_date || r.record_date}</td><td>{r.created_by}<div className="text-xs text-slate-400">{r.updated_by && r.updated_by !== r.created_by ? `изменил: ${r.updated_by}` : ''}</div></td><td><StatusBadge value={r.workflow_status} /></td><td><div className="font-medium">{r.operation_type || r.movement_type ? operationLabel(r.operation_type || r.movement_type) : r.counterparty}</div><div className="max-w-72 truncate text-xs text-slate-500" title={r.basis || r.change_reason || r.description}>{[r.isin || r.related_isin, r.basis || r.change_reason || r.description].filter(Boolean).join(' · ')}</div></td><td className="text-right font-mono">{formatNumber(r.amount_kzt ?? r.amount, 2)}</td><td>{canApprove && <div className="flex justify-end gap-1"><button className="btn-secondary px-2 py-1 text-emerald-700" onClick={() => onApprove(r.entity, r.id)} title="Согласовать"><Check className="h-4 w-4" /></button><button className="btn-secondary px-2 py-1 text-red-600" onClick={() => onReject(r.entity, r.id)} title="Отклонить"><X className="h-4 w-4" /></button></div>}</td></tr>)}{!rows.length && <tr><td colSpan={8} className="py-10 text-center text-slate-400">Очередь согласования пуста</td></tr>}</tbody></table></div></>
}

function Field({ label, children, wide = false }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return <label className={wide ? 'sm:col-span-2' : ''}><span className="mb-1 block text-xs font-semibold text-slate-600">{label}</span>{children}</label>
}

const CASH_TYPES: Array<[string, string]> = [
  ['RECEIPT', 'Поступление'], ['INITIAL_BALANCE', 'Входящий остаток'], ['CONTRIBUTION', 'Взнос в портфель'],
  ['COUPON', 'Купон'], ['REDEMPTION', 'Погашение'], ['PAYMENT', 'Списание'], ['WITHDRAWAL', 'Изъятие из портфеля'],
  ['COMMISSION', 'Комиссия'], ['CORRECTION', 'Корректировка (±)'], ['OTHER', 'Прочее (±)'],
]

function OperationEditor({ open, editor, reportDate, cdus, onClose, onSaved }: { open: boolean; editor: { kind: EditorKind; row?: Row; parent?: Row } | null; reportDate: string; cdus: CDU[]; onClose: () => void; onSaved: () => void }) {
  const [saving, setSaving] = useState(false)
  const accountsQ = useQuery<Array<{ account: string; currency?: string; cdu_id?: number; source: string }>>({
    queryKey: ['known-accounts'],
    queryFn: async () => (await api.get('/accounting/accounts')).data,
    enabled: open && editor?.kind === 'cash',
  })
  const accounts = accountsQ.data ?? []
  if (!editor) return null
  const { kind, row, parent } = editor
  const title = kind === 'trade' ? 'Ручная сделка' : kind === 'cash' ? 'Движение денег' : kind === 'receivable' ? 'Дебиторская задолженность' : 'Операция по дебиторке'
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setSaving(true)
    const payload = Object.fromEntries(new FormData(event.currentTarget).entries())
    try {
      if (kind === 'trade') await (row ? api.patch(`/accounting/trades/${row.id}`, payload) : api.post('/accounting/trades', payload))
      if (kind === 'cash') await (row ? api.patch(`/accounting/cash-movements/${row.id}`, payload) : api.post('/accounting/cash-movements', payload))
      if (kind === 'receivable') await (row ? api.patch(`/accounting/receivables/${row.id}`, payload) : api.post('/accounting/receivables', payload))
      if (kind === 'receivable-tx') await api.post(`/accounting/receivables/${parent!.id}/transactions`, payload)
      toast.success('Операция сохранена и отправлена на согласование.'); onSaved()
    } catch (error: unknown) { toast.error(apiErrorMessage(error, 'Не удалось сохранить операцию')) } finally { setSaving(false) }
  }
  return <Modal open={open} onClose={onClose} title={title} description="После сохранения запись не участвует в расчётах до согласования другим пользователем" size="lg">
    <form onSubmit={submit} className="grid max-h-[70vh] grid-cols-1 gap-3 overflow-y-auto pr-1 sm:grid-cols-2">
      {kind !== 'receivable-tx' && <Field label="Портфель / ЧДУ"><select name="cdu_id" required className="input w-full" defaultValue={value(row, 'cdu_id')}><option value="">Выберите</option>{cdus.map((cdu) => <option key={cdu.id} value={cdu.id}>{cdu.short_name} — {cdu.name}</option>)}</select></Field>}
      {kind === 'trade' && <>
        <Field label="Дата сделки"><input name="trade_date" required type="date" className="input w-full" defaultValue={value(row, 'trade_date', reportDate)} /></Field>
        <Field label="Дата расчётов"><input name="value_date" required type="date" className="input w-full" defaultValue={value(row, 'value_date', reportDate)} /></Field>
        <Field label="Вид сделки"><select name="operation_type" className="input w-full" defaultValue={value(row, 'operation_type', 'BUY')}>{['BUY','SELL','REPO_OPEN','REPO_CLOSE','COUPON','REDEMPTION','DEPOSIT_OPEN','DEPOSIT_CLOSE','FX_BUY','FX_SELL','OTHER'].map((x) => <option key={x} value={x}>{operationLabel(x)}</option>)}</select></Field>
        <Field label="Категория"><select name="instrument_category" className="input w-full" defaultValue={value(row, 'instrument_category', 'OTHER')}>{['GOV_BONDS','AGENCY_BONDS','MFO_BONDS','FOREIGN_BONDS','REVERSE_REPO','DEPOSIT','OTHER'].map((x) => <option key={x} value={x}>{categoryLabel(x)}</option>)}</select></Field>
        <Field label="ISIN"><input name="isin" className="input w-full" defaultValue={value(row, 'isin')} /></Field>
        <Field label="ID сделки"><input name="deal_id" className="input w-full" defaultValue={value(row, 'deal_id')} /></Field>
        <Field label="Сумма (знак определится по типу)"><input name="amount_kzt" required type="number" step="any" className="input w-full" defaultValue={Math.abs(value(row, 'amount_kzt', 0))} /></Field>
        <Field label="Количество / номинал"><input name="face_value" type="number" step="any" className="input w-full" defaultValue={value(row, 'face_value')} /></Field>
        <Field label="Цена"><input name="market_price" type="number" step="any" className="input w-full" defaultValue={value(row, 'market_price')} /></Field>
        <Field label="YTM (доля: 0.0666)"><input name="ytm" type="number" step="any" className="input w-full" defaultValue={value(row, 'ytm')} /></Field>
        <Field label="Ставка РЕПО (доля)"><input name="repo_rate_pct" type="number" step="any" className="input w-full" defaultValue={value(row, 'repo_rate_pct')} /></Field>
        <Field label="Срок РЕПО, дней"><input name="repo_term_days" type="number" className="input w-full" defaultValue={value(row, 'repo_term_days')} /></Field>
        <Field label="Сумма закрытия РЕПО"><input name="repo_buyback_sum" type="number" step="any" className="input w-full" defaultValue={value(row, 'repo_buyback_sum')} /></Field>
      </>}
      {kind === 'cash' && <>
        <Field label="Счёт (IBAN)"><input name="account" list="known-accounts" className="input w-full font-mono uppercase" placeholder="KZ…" defaultValue={value(row, 'account')} /><datalist id="known-accounts">{accounts.map((a) => <option key={a.account} value={a.account}>{a.currency ?? ''} {a.source === 'statement' ? '· из выписки' : ''}</option>)}</datalist></Field>
        <Field label="Дата операции"><input name="operation_date" required type="date" className="input w-full" defaultValue={value(row, 'operation_date', reportDate)} /></Field>
        <Field label="Вид движения"><select name="movement_type" className="input w-full" defaultValue={value(row, 'movement_type', 'RECEIPT')}>{CASH_TYPES.map(([x, label]) => <option key={x} value={x}>{label}</option>)}</select></Field>
        <Field label="Сумма (знак определяется видом; для «Корректировки» укажите знак)"><input name="amount" required type="number" step="any" className="input w-full" defaultValue={value(row, 'amount')} /></Field>
        <Field label="Валюта"><select name="currency" required className="input w-full" defaultValue={value(row, 'currency', 'KZT')}>{['KZT','USD','EUR','RUB','CNY'].map((c) => <option key={c}>{c}</option>)}</select></Field>
        <Field label="Связанная сделка ID"><input name="related_trade_id" type="number" className="input w-full" defaultValue={value(row, 'related_trade_id')} /></Field>
        <Field label="ISIN"><input name="related_isin" className="input w-full" defaultValue={value(row, 'related_isin')} /></Field>
        <Field label="Назначение платежа" wide><textarea name="basis" required className="input min-h-20 w-full" defaultValue={value(row, 'basis')} /></Field>
      </>}
      {kind === 'receivable' && <>
        <Field label="Дата признания"><input name="record_date" required type="date" className="input w-full" defaultValue={value(row, 'record_date', reportDate)} /></Field>
        <Field label="Плановая дата погашения"><input name="due_date" type="date" className="input w-full" defaultValue={value(row, 'due_date')} /></Field>
        <Field label="Контрагент"><input name="counterparty" required className="input w-full" defaultValue={value(row, 'counterparty')} /></Field>
        <Field label="ISIN (при наличии)"><input name="isin" className="input w-full" defaultValue={value(row, 'isin')} /></Field>
        <Field label="Первоначальная сумма"><input name="amount" required type="number" min="0" step="any" className="input w-full" defaultValue={value(row, 'amount')} /></Field>
        <Field label="Валюта"><input name="currency" required className="input w-full" defaultValue={value(row, 'currency', 'KZT')} /></Field>
        <Field label="Сумма в KZT"><input name="amount_kzt" type="number" step="any" className="input w-full" defaultValue={value(row, 'amount_kzt')} /></Field>
        <Field label="Основание возникновения" wide><textarea name="description" required className="input min-h-20 w-full" defaultValue={value(row, 'description')} /></Field>
      </>}
      {kind === 'receivable-tx' && <>
        <Field label="Дебиторка"><input readOnly className="input w-full bg-slate-50" value={`${parent?.counterparty} · остаток ${formatNumber(parent?.balance_kzt, 2)}`} /></Field>
        <Field label="Дата операции"><input name="operation_date" required type="date" className="input w-full" defaultValue={reportDate} /></Field>
        <Field label="Операция"><select name="operation_type" className="input w-full">{['REPAYMENT', 'WRITE_OFF', 'ADJUSTMENT'].map((x) => <option key={x} value={x}>{operationLabel(x)}</option>)}</select></Field>
        <Field label="Сумма"><input name="amount" required type="number" step="any" className="input w-full" /></Field>
        <Field label="Валюта"><input name="currency" className="input w-full" defaultValue={parent?.currency || 'KZT'} /></Field>
        <Field label="Основание" wide><textarea name="basis" required className="input min-h-20 w-full" /></Field>
      </>}
      {kind !== 'receivable-tx' && <Field label="Причина ручного действия" wide><textarea name="change_reason" required className="input min-h-20 w-full" defaultValue={value(row, 'change_reason')} /></Field>}
      <div className="flex justify-end gap-2 pt-2 sm:col-span-2"><button type="button" className="btn-secondary" onClick={onClose}>Отмена</button><button disabled={saving} className="btn-primary"><BadgeDollarSign className="h-4 w-4" />{saving ? 'Сохранение…' : 'Отправить на согласование'}</button></div>
    </form>
  </Modal>
}
