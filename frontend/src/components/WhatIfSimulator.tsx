import { FormEvent, useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight, FlaskConical, ShieldCheck, Sparkles } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { apiErrorMessage } from '@/lib/notifications'
import { formatNumber, formatPct } from '@/lib/format'
import type { CDUBlock } from '@/lib/types'

const CATEGORIES = [
  ['GOV_BONDS', 'Государственные ценные бумаги'],
  ['REVERSE_REPO', 'Обратное РЕПО'],
  ['MFO_BONDS', 'Облигации МФО'],
  ['AGENCY_BONDS', 'Агентские облигации'],
  ['FOREIGN_BONDS', 'Иностранные облигации'],
  ['DEPOSIT', 'Депозиты'],
  ['CASH', 'Денежные средства'],
] as const

interface SimulationResult {
  report_date: string
  cdu: { id: number; name: string }
  transaction: { operation_type: string; category: string; category_label: string; amount_kzt: number; duration: number }
  portfolio: {
    total_before: number; total_after: number
    duration_before: number; duration_after: number; duration_delta: number
    benchmark_duration: number | null; duration_lower: number | null; duration_upper: number | null
    duration_status_before: string; duration_status_after: string
  }
  fund: { duration_before: number; duration_after: number; duration_delta: number }
  limit: {
    category_value_before: number; category_value_after: number
    pct_before: number; pct_after: number; min_pct: number; max_pct: number
    hard_status_before: string; hard_status_after: string
    soft_status_before: string; soft_status_after: string
  }
  persisted: boolean
}

function DeltaValue({ before, after, format }: { before: number; after: number; format: (value: number) => string }) {
  const delta = after - before
  return (
    <div className="flex items-center gap-2 font-mono text-sm">
      <span className="text-slate-500">{format(before)}</span>
      <ArrowRight className="h-4 w-4 text-slate-400" />
      <span className="font-bold text-slate-900">{format(after)}</span>
      <span className={delta > 0 ? 'text-emerald-700' : delta < 0 ? 'text-rose-700' : 'text-slate-500'}>
        ({delta > 0 ? '+' : ''}{format(delta)})
      </span>
    </div>
  )
}

export default function WhatIfSimulator({ reportDate, blocks }: { reportDate: string; blocks: CDUBlock[] }) {
  const [cduId, setCduId] = useState<number | ''>(blocks[0]?.cdu_id ?? '')
  const [operationType, setOperationType] = useState('BUY')
  const [category, setCategory] = useState('GOV_BONDS')
  const [amount, setAmount] = useState('100000000')
  const [duration, setDuration] = useState('2')

  useEffect(() => {
    if (!cduId && blocks[0]) setCduId(blocks[0].cdu_id)
  }, [blocks, cduId])

  const simulation = useMutation<SimulationResult>({
    mutationFn: async () => (await api.post('/dashboard/what-if', {
      report_date: reportDate,
      cdu_id: cduId,
      operation_type: operationType,
      category,
      amount_kzt: Number(amount),
      duration: Number(duration),
    })).data,
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось рассчитать сценарий')),
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    simulation.mutate()
  }
  const result = simulation.data

  return (
    <section className="overflow-hidden rounded-2xl border border-indigo-200 bg-gradient-to-br from-indigo-50 via-white to-violet-50 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-indigo-100 px-5 py-4">
        <div>
          <h2 className="flex items-center gap-2 font-bold text-indigo-950"><FlaskConical className="h-5 w-5" /> Песочница / What-If</h2>
          <p className="mt-0.5 text-sm text-indigo-700/80">Виртуальная сделка не сохраняется и не влияет на рабочие данные.</p>
        </div>
        <span className="inline-flex items-center gap-1 rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-indigo-700 ring-1 ring-indigo-200"><Sparkles className="h-3.5 w-3.5" /> Режим симуляции</span>
      </div>

      <form onSubmit={submit} className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-6">
        <label className="xl:col-span-2"><span className="mb-1 block text-xs font-semibold text-slate-600">Портфель</span><select className="input w-full" value={cduId} onChange={(e) => setCduId(Number(e.target.value))} required><option value="">Выберите ЧДУ</option>{blocks.map((block) => <option key={block.cdu_id} value={block.cdu_id}>{block.cdu_short} — {block.cdu_name}</option>)}</select></label>
        <label><span className="mb-1 block text-xs font-semibold text-slate-600">Операция</span><select className="input w-full" value={operationType} onChange={(e) => setOperationType(e.target.value)}><option value="BUY">Покупка</option><option value="SELL">Продажа</option></select></label>
        <label><span className="mb-1 block text-xs font-semibold text-slate-600">Категория</span><select className="input w-full" value={category} onChange={(e) => setCategory(e.target.value)}>{CATEGORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label><span className="mb-1 block text-xs font-semibold text-slate-600">Сумма, ₸</span><input className="input w-full font-mono" type="number" min="0.01" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required /></label>
        <label><span className="mb-1 block text-xs font-semibold text-slate-600">Дюрация сделки</span><div className="flex gap-2"><input className="input min-w-0 flex-1 font-mono" type="number" min="0" step="0.01" value={duration} onChange={(e) => setDuration(e.target.value)} required /><button className="btn-primary shrink-0" disabled={simulation.isPending || !cduId}>{simulation.isPending ? 'Расчёт…' : 'Рассчитать'}</button></div></label>
      </form>

      {result && (
        <div className="grid gap-3 border-t border-indigo-100 bg-white/70 p-4 lg:grid-cols-3">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-xs font-bold uppercase tracking-wide text-slate-500">Дюрация портфеля</div>
            <div className="mt-2"><DeltaValue before={result.portfolio.duration_before} after={result.portfolio.duration_after} format={(value) => formatNumber(value, 4)} /></div>
            <div className="mt-2 text-xs text-slate-500">Коридор MBM: {formatNumber(result.portfolio.duration_lower, 2)}–{formatNumber(result.portfolio.duration_upper, 2)}</div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-xs font-bold uppercase tracking-wide text-slate-500">Дюрация Фонда</div>
            <div className="mt-2"><DeltaValue before={result.fund.duration_before} after={result.fund.duration_after} format={(value) => formatNumber(value, 4)} /></div>
            <div className="mt-2 text-xs text-slate-500">Общий эффект с учётом веса выбранного ЧДУ</div>
          </div>
          <div className={`rounded-xl border p-4 ${result.limit.hard_status_after === 'breach' ? 'border-rose-200 bg-rose-50' : result.limit.soft_status_after === 'breach' ? 'border-amber-200 bg-amber-50' : 'border-emerald-200 bg-emerald-50'}`}>
            <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-slate-600">{result.limit.hard_status_after === 'breach' ? <AlertTriangle className="h-4 w-4 text-rose-600" /> : <ShieldCheck className="h-4 w-4 text-emerald-600" />} Лимит категории</div>
            <div className="mt-2"><DeltaValue before={result.limit.pct_before} after={result.limit.pct_after} format={(value) => formatPct(value)} /></div>
            <div className="mt-2 text-xs text-slate-600">Допустимо: {formatPct(result.limit.min_pct)}–{formatPct(result.limit.max_pct)} · после сделки: {result.limit.hard_status_after === 'breach' ? 'нарушение' : result.limit.soft_status_after === 'breach' ? 'предупреждение' : 'в норме'}</div>
          </div>
        </div>
      )}
    </section>
  )
}
