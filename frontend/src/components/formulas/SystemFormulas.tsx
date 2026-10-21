import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BookOpen, CheckCircle2, Info, Loader2, MapPin, XCircle } from 'lucide-react'
import clsx from 'clsx'

import { api } from '@/lib/api'
import { useWorkContextStore } from '@/lib/workContext'
import { formatNumber } from '@/lib/format'
import type { CDU } from '@/lib/types'
import { TokenFormula, type Token } from './FormulaChips'

interface ParamValue { code: string; label: string; value: number | string; unit: string }
export interface SysFormula {
  code: string; group: string; title: string; tokens: Token[]; plain: string; where: string; source: string
  price_rule?: string; params: string[]; param_values: ParamValue[]
}
interface Input { label: string; value: number | string | null; unit: string; source: string | null }
interface Example {
  choices?: Array<{ value: string; label: string }>
  item?: string; item_label?: string
  inputs?: Input[]; steps?: string[]
  result?: { label: string; value: number | string | null; unit: string }
  system_value?: number | null
  note?: string | null
  table?: Array<Record<string, number | string | null>>
  extra?: { label: string; value: number | null; system_value: number | null }
  empty?: string
  cdu_id?: number
}

const UNIT: Record<string, string> = { KZT: '₸', '₸': '₸', '%': '%', 'дн.': 'дн.', '×': '', '': '' }

function fmtValue(v: number | string | null | undefined, unit: string): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string') return v
  const digits = unit === '%' ? 4 : unit === 'дн.' ? 0 : Math.abs(v) < 100 && v % 1 !== 0 ? 6 : 2
  const s = formatNumber(v, digits)
  const u = UNIT[unit] ?? unit
  return u ? `${s} ${u}` : s
}

export function paramText(p: ParamValue): string {
  if (typeof p.value === 'string') return p.value === 'market' ? 'рыночная' : p.value === 'risk_parameters' ? 'по риск-парам.' : p.value
  return `${formatNumber(p.value, p.unit === '×' ? 2 : p.value % 1 ? 4 : 0)}${p.unit === '×' ? '' : ` ${p.unit}`}`
}

export default function SystemFormulas({ onParam }: { onParam: (code: string) => void }) {
  const list = useQuery<SysFormula[]>({ queryKey: ['formulas-system'], queryFn: async () => (await api.get('/formulas/system')).data })
  const [code, setCode] = useState<string>('BOND_VALUE')
  const current = list.data?.find((f) => f.code === code) ?? list.data?.[0]
  const groups = useMemo(() => {
    const g: Record<string, SysFormula[]> = {}
    for (const f of list.data ?? []) (g[f.group] ??= []).push(f)
    return Object.entries(g)
  }, [list.data])

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[260px_1fr]">
      <nav className="card h-max p-2">
        {list.isLoading && <div className="p-3 text-sm text-slate-500">Загрузка…</div>}
        {groups.map(([group, items]) => (
          <div key={group} className="mb-2">
            <div className="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{group}</div>
            {items.map((f) => (
              <button key={f.code} type="button" onClick={() => setCode(f.code)}
                className={clsx('block w-full rounded-lg px-2.5 py-1.5 text-left text-sm transition',
                  current?.code === f.code ? 'bg-emerald-50 font-semibold text-emerald-800' : 'text-slate-700 hover:bg-slate-50')}>
                {f.title}
              </button>
            ))}
          </div>
        ))}
      </nav>
      {current && <FormulaCard f={current} onParam={onParam} />}
    </div>
  )
}

function FormulaCard({ f, onParam }: { f: SysFormula; onParam: (code: string) => void }) {
  const params = Object.fromEntries(f.param_values.map((p) => [p.code, paramText(p)]))
  return (
    <div className="space-y-4">
      <div className="card space-y-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <h2 className="text-lg font-semibold text-slate-900">{f.title}</h2>
          <span className="badge-neutral">формула системы · не редактируется</span>
        </div>
        <div className="rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-3">
          <TokenFormula tokens={f.tokens} params={params} onParam={onParam} />
        </div>
        <p className="text-sm leading-6 text-slate-700">{f.plain}</p>
        {f.price_rule && <p className="text-sm text-slate-600"><b className="text-slate-700">Цена:</b> {f.price_rule.replace(/^Цена:\s*/, '')}</p>}
        <div className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
          <div className="flex gap-2 text-slate-600"><MapPin className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" /><span><b className="text-slate-700">Где используется:</b> {f.where}</span></div>
          <div className="flex gap-2 text-slate-600"><BookOpen className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" /><span><b className="text-slate-700">Источник:</b> {f.source}</span></div>
        </div>
        {f.param_values.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3 text-sm">
            <span className="text-slate-500">Можно настроить:</span>
            {f.param_values.map((p) => (
              <button key={p.code} type="button" onClick={() => onParam(p.code)}
                className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-0.5 text-[13px] text-amber-900 ring-1 ring-inset ring-amber-600/30 hover:bg-amber-100">
                {p.label}: <b className="tabular-nums">{paramText(p)}</b>
              </button>
            ))}
          </div>
        )}
      </div>
      <ExamplePanel code={f.code} />
    </div>
  )
}

function ExamplePanel({ code }: { code: string }) {
  const workDate = useWorkContextStore((s) => s.workDate)
  const setWorkDate = useWorkContextStore((s) => s.setWorkDate)
  const cdus = useQuery<CDU[]>({ queryKey: ['cdus'], queryFn: async () => (await api.get('/settings/cdus')).data })
  const active = (cdus.data ?? []).filter((c) => c.is_active)
  const [cduId, setCduId] = useState<number | null>(null)
  const [item, setItem] = useState<string | null>(null)
  useEffect(() => { setItem(null) }, [code, cduId, workDate])

  const ex = useQuery<Example>({
    queryKey: ['formula-example', code, cduId, workDate, item],
    placeholderData: (prev) => prev,
    queryFn: async () => (await api.get(`/formulas/system/${code}/example`, {
      params: { date: workDate, ...(cduId !== null ? { cdu_id: cduId } : {}), ...(item ? { item } : {}) },
    })).data,
  })
  const d = ex.data
  const resultNum = typeof d?.result?.value === 'number' ? d.result.value : null
  const matches = resultNum !== null && d?.system_value !== undefined && d?.system_value !== null
    ? Math.abs(resultNum - d.system_value) <= Math.max(0.01, Math.abs(d.system_value) * 1e-6) : null

  return (
    <div className="card p-5">
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="mr-auto">
          <div className="text-base font-semibold text-slate-900">Пример на ваших данных</div>
          <div className="text-xs text-slate-500">Пересчитываем формулу по шагам и сравниваем с тем, что использует система</div>
        </div>
        <label className="w-44"><span className="field-label">ЧДУ</span>
          <select className="input-sm" value={cduId ?? d?.cdu_id ?? ''} onChange={(e) => setCduId(Number(e.target.value))}>
            {active.map((c) => <option key={c.id} value={c.id}>{c.short_name || c.name}</option>)}
          </select>
        </label>
        <label className="w-40"><span className="field-label">Дата</span>
          <input type="date" className="input-sm" value={workDate} onChange={(e) => setWorkDate(e.target.value)} />
        </label>
        {d?.choices && d.choices.length > 0 && (
          <label className="w-72"><span className="field-label">{code.startsWith('REPO') || code.startsWith('DEPOSIT') ? 'Сделка' : 'Бумага'}</span>
            <select className="input-sm" value={d.item ?? ''} onChange={(e) => setItem(e.target.value)}>
              {d.choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </label>
        )}
      </div>

      {ex.isLoading && <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Считаем…</div>}
      {d?.empty && <div className="rounded-xl bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">{d.empty}</div>}

      {d && !d.empty && (
        <div className="space-y-4">
          {d.inputs && d.inputs.length > 0 && (
            <div>
              <div className="field-label mb-1.5">1. Исходные данные</div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
                {d.inputs.map((i) => (
                  <div key={i.label} className="rounded-xl border border-sky-100 bg-sky-50/50 px-3 py-2">
                    <div className="text-xs font-medium text-sky-800">{i.label}</div>
                    <div className="text-sm font-semibold tabular-nums text-slate-900">{fmtValue(i.value, i.unit)}</div>
                    {i.source && <div className="text-[11px] text-slate-500">{i.source}</div>}
                  </div>
                ))}
              </div>
            </div>
          )}
          {d.table && d.table.length > 0 && <ExampleTable rows={d.table} />}
          {d.steps && d.steps.length > 0 && (
            <div>
              <div className="field-label mb-1.5">{d.inputs?.length ? '2. Расчёт' : 'Расчёт'}</div>
              <ol className="space-y-1 rounded-xl bg-slate-900 px-4 py-3 font-mono text-[13px] text-emerald-100">
                {d.steps.map((s, i) => <li key={i}><span className="mr-2 text-slate-500">{i + 1}.</span>{s}</li>)}
              </ol>
            </div>
          )}
          {d.result && (
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50/60 px-4 py-3">
              <div>
                <div className="text-xs text-emerald-800">{d.result.label}</div>
                <div className="text-xl font-bold tabular-nums text-emerald-900">{fmtValue(d.result.value, d.result.unit)}</div>
              </div>
              {d.system_value !== undefined && d.system_value !== null && (
                <div className="ml-auto text-right">
                  <div className="text-xs text-slate-500">В системе</div>
                  <div className="text-sm font-semibold tabular-nums text-slate-800">{fmtValue(d.system_value, d.result.unit)}</div>
                  {matches !== null && (matches
                    ? <span className="badge-ok mt-1"><CheckCircle2 className="h-3 w-3" /> совпадает</span>
                    : <span className="badge-warn mt-1"><XCircle className="h-3 w-3" /> разница {formatNumber(resultNum! - d.system_value, 6)}</span>)}
                </div>
              )}
              {d.extra && (
                <div className="w-full border-t border-emerald-200 pt-2 text-sm text-slate-700">
                  {d.extra.label}: <b className="tabular-nums">{formatNumber(d.extra.value, 4)}</b>
                  {d.extra.system_value !== null && <span className="text-slate-500"> · в системе {formatNumber(d.extra.system_value, 4)}</span>}
                </div>
              )}
            </div>
          )}
          {d.note && <div className="flex gap-2 text-xs text-slate-500"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />{d.note}</div>}
        </div>
      )}
    </div>
  )
}

function ExampleTable({ rows }: { rows: Array<Record<string, number | string | null>> }) {
  const cols = Object.keys(rows[0])
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="detail-table w-full">
        <thead><tr>{cols.map((c) => <th key={c} className={c === 'Категория' || c === 'Статус' ? '' : 'num'}>{c}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {cols.map((c) => {
                const v = r[c]
                if (c === 'Статус') return <td key={c}><span className={v === 'нарушение' ? 'badge-breach' : 'badge-ok'}>{v}</span></td>
                if (typeof v === 'number') return <td key={c} className="num">{formatNumber(v, c.includes('%') || c === 'Дюрация' ? 4 : 2)}</td>
                return <td key={c}>{v ?? '—'}</td>
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
