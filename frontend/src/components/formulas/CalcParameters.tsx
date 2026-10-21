import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Calculator, History, Pencil, RotateCcw, Save, X } from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'

import { api } from '@/lib/api'
import { apiErrorMessage, notificationText } from '@/lib/notifications'
import { useAuthStore } from '@/lib/auth'
import { useWorkContextStore } from '@/lib/workContext'
import { formatDate, formatNumber } from '@/lib/format'

interface Param {
  code: string; label: string; group: string; unit: string; kind: 'float' | 'int' | 'choice'
  default: number | string; value: number | string; min: number | null; max: number | null
  choices: Array<{ value: string; label: string }>
  description: string; used_in: string; formula: string | null; is_default: boolean
  updated_by: string | null; updated_at: string | null
  history: Array<{ old: string | null; new: string; reason: string | null; by: string | null; at: string | null }>
}

function show(p: Param, v: number | string | null): string {
  if (v === null || v === undefined || v === '') return '—'
  if (p.kind === 'choice') return p.choices.find((c) => c.value === v)?.label ?? String(v)
  const n = typeof v === 'number' ? v : Number(v)
  if (Number.isNaN(n)) return String(v)
  const digits = p.kind === 'int' ? 0 : Math.min(6, Math.max(2, (String(n).split('.')[1] ?? '').length))
  return `${formatNumber(n, digits)}${p.unit && p.unit !== '×' ? ` ${p.unit}` : ''}`
}

export default function CalcParameters({ focus }: { focus?: string | null }) {
  const qc = useQueryClient()
  const canEdit = useAuthStore((s) => s.can('formulas.edit'))
  const workDate = useWorkContextStore((s) => s.workDate)
  const list = useQuery<Param[]>({ queryKey: ['formula-params'], queryFn: async () => (await api.get('/formulas/parameters')).data })
  const [editing, setEditing] = useState<string | null>(null)
  const [changed, setChanged] = useState(false)
  const groups = useMemo(() => {
    const g: Record<string, Param[]> = {}
    for (const p of list.data ?? []) (g[p.group] ??= []).push(p)
    return Object.entries(g)
  }, [list.data])

  const recalc = useMutation({
    mutationFn: async () => (await api.post('/calculate/', { report_date: workDate, recalculate: true })).data,
    onSuccess: () => {
      toast.success(`Сводка за ${formatDate(workDate)} пересчитана с новыми параметрами.`)
      setChanged(false)
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      qc.invalidateQueries({ queryKey: ['indicator-values'] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, `Не удалось пересчитать сводку за ${formatDate(workDate)}`)),
  })

  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-center gap-3 px-4 py-3 text-sm text-slate-600">
        <span>Сами формулы фиксированы — они повторяют отчёт о рисках. Здесь меняются только их числовые настройки.
          Каждое изменение сохраняется в истории с причиной и автором.</span>
        {changed && (
          <button type="button" className="btn-primary ml-auto h-9" disabled={recalc.isPending} onClick={() => recalc.mutate()}>
            <Calculator className="h-4 w-4" /> Пересчитать сводку за {formatDate(workDate)}
          </button>
        )}
      </div>
      {groups.map(([group, items]) => (
        <section key={group} className="card overflow-hidden">
          <div className="border-b border-slate-100 bg-slate-50/70 px-4 py-2 text-sm font-semibold text-slate-800">{group}</div>
          <div className="divide-y divide-slate-100">
            {items.map((p) => (
              <ParamRow key={p.code} p={p} canEdit={canEdit} focused={focus === p.code}
                editing={editing === p.code} onEdit={() => setEditing(p.code)} onClose={() => setEditing(null)}
                onSaved={() => { setEditing(null); setChanged(true); qc.invalidateQueries({ queryKey: ['formula-params'] }); qc.invalidateQueries({ queryKey: ['formulas-system'] }) }} />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

function ParamRow({ p, canEdit, focused, editing, onEdit, onClose, onSaved }: {
  p: Param; canEdit: boolean; focused: boolean; editing: boolean; onEdit: () => void; onClose: () => void; onSaved: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [value, setValue] = useState(String(p.value))
  const [reason, setReason] = useState('')
  const [showHistory, setShowHistory] = useState(false)
  useEffect(() => { if (focused) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }, [focused])
  useEffect(() => { if (editing) { setValue(p.kind === 'choice' ? String(p.value) : String(p.value).replace('.', ',')); setReason('') } }, [editing, p.value, p.kind])

  const save = useMutation({
    mutationFn: async () => (await api.put(`/formulas/parameters/${p.code}`, { value, reason })).data,
    onSuccess: (r) => { toast.success(notificationText(r.message, 'Параметр расчёта сохранён'), { duration: 6000 }); onSaved() },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось сохранить параметр расчёта')),
  })
  const reset = useMutation({
    mutationFn: async () => (await api.post(`/formulas/parameters/${p.code}/reset`, {})).data,
    onSuccess: () => { toast.success('Параметр возвращён к значению по умолчанию.'); onSaved() },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось восстановить значение параметра')),
  })

  return (
    <div ref={ref} className={clsx('px-4 py-3 transition', focused && 'bg-amber-50/60')}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-[260px] flex-1">
          <div className="text-sm font-semibold text-slate-900">{p.label}</div>
          <div className="text-xs leading-5 text-slate-600">{p.description}</div>
          <div className="text-[11px] text-slate-400">Где влияет: {p.used_in}
            {p.min !== null && p.max !== null && p.kind !== 'choice' && <> · допустимо от {formatNumber(p.min, p.kind === 'int' ? 0 : 2)} до {formatNumber(p.max, p.kind === 'int' ? 0 : 2)}</>}
          </div>
        </div>
        {!editing && (
          <div className="flex items-center gap-2">
            <div className="text-right">
              <div className="text-base font-bold tabular-nums text-slate-900">{show(p, p.value)}</div>
              {p.is_default
                ? <span className="badge-neutral">по умолчанию</span>
                : <span className="badge-warn" title={p.updated_at ? `${p.updated_by ?? ''}, ${formatDate(p.updated_at)}` : ''}>
                    изменён · по умолчанию {show(p, p.default)}</span>}
            </div>
            {canEdit && <button type="button" className="btn-ghost h-8 px-2" onClick={onEdit} title="Изменить"><Pencil className="h-4 w-4" /></button>}
            {canEdit && !p.is_default && (
              <button type="button" className="btn-ghost h-8 px-2" title="Вернуть значение по умолчанию"
                disabled={reset.isPending} onClick={() => reset.mutate()}><RotateCcw className="h-4 w-4" /></button>
            )}
            {p.history.length > 0 && (
              <button type="button" className="btn-ghost h-8 px-2" title="История изменений" onClick={() => setShowHistory((v) => !v)}>
                <History className="h-4 w-4" />
              </button>
            )}
          </div>
        )}
      </div>
      {editing && (
        <div className="mt-3 flex flex-wrap items-end gap-2 rounded-xl border border-emerald-200 bg-emerald-50/40 p-3">
          <label className="w-60"><span className="field-label">Новое значение</span>
            {p.kind === 'choice'
              ? <select className="input-sm" value={value} onChange={(e) => setValue(e.target.value)}>
                  {p.choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              : <div className="flex items-center gap-1"><input className="input-sm text-right" value={value} autoFocus
                  onChange={(e) => setValue(e.target.value)} /><span className="text-xs text-slate-500">{p.unit}</span></div>}
          </label>
          <label className="min-w-[260px] flex-1"><span className="field-label">Причина изменения (обязательно)</span>
            <input className="input-sm" value={reason} placeholder="например: решение ИК от 05.10.2026"
              onChange={(e) => setReason(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && reason.trim()) save.mutate() }} />
          </label>
          <button type="button" className="btn-primary h-8 px-3" disabled={!reason.trim() || save.isPending} onClick={() => save.mutate()}>
            <Save className="h-4 w-4" /> Сохранить
          </button>
          <button type="button" className="btn-ghost h-8 px-2" onClick={onClose}><X className="h-4 w-4" /></button>
        </div>
      )}
      {showHistory && !editing && (
        <table className="detail-table mt-2 w-full text-xs">
          <thead><tr><th>Когда</th><th>Кто</th><th>Было</th><th>Стало</th><th>Причина</th></tr></thead>
          <tbody>
            {p.history.map((h, i) => (
              <tr key={i}>
                <td>{h.at ? new Date(h.at).toLocaleString('ru-RU') : '—'}</td><td>{h.by ?? '—'}</td>
                <td>{show(p, h.old)}</td><td>{show(p, h.new)}</td><td>{h.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
