import { Fragment, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, CheckCircle2, Clock, Download, FileSpreadsheet, GitCompare, Info, Link2, Loader2,
  RefreshCw, UploadCloud, X, XCircle,
} from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'

import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { useWorkContextStore } from '@/lib/workContext'
import { formatDate, formatNumber } from '@/lib/format'
import { PageHeader } from '@/components/ui'
import type { CDU } from '@/lib/types'
import { fieldLabel, processStatusLabel, sourceLabel } from '@/lib/displayLabels'
import { apiErrorMessage, notificationText } from '@/lib/notifications'

// ───────────────────────── types ─────────────────────────

interface Cell { id: number; status: string; deviation: number | null; expected: number | null; actual: number | null; note?: string | null; counts?: Record<string, number> | null }
interface Row { cdu_id: number; cdu_name: string; portfolio_type: string; file: { doc_id: number; file_name: string; uploaded_at: string | null } | null; results: Record<string, Cell> }
interface Overview {
  date: string
  types: Array<{ code: string; label: string; main?: boolean }>
  rows: Row[]
  unbound_files: Array<{ doc_id: number; file_name: string; doc_date: string | null; uploaded_at: string | null; cdu_name_in_file: string | null }>
  file_dates: string[]
}

interface SideSec { lots: number; quantity: number | null; face_value: number; price: number | null; accrued: number; value: number; price_source?: string | null; price_date?: string | null; rows?: number[]; quantity_from_cdu_nominal?: boolean }
interface SecLine { isin: string; ticker: string | null; name: string | null; status: string; fields: string[]; reasons: string[]; delta_value: number; ours?: SideSec; cdu?: SideSec }
interface RepoSide { open_date: string | null; close_date: string | null; open_amount: number; close_amount: number | null; accrued: number; value?: number | null; value_effective?: number; rate_pct?: number | null; isin?: string | null; collateral?: string | null; quantity?: number | null; deal_id?: string | null; closed?: boolean }
interface RepoLine { status: string; isin: string | null; fields: string[]; reasons: string[]; delta_value: number; ours: RepoSide | null; cdu: RepoSide | null }
interface Details {
  status: string
  note?: string
  summary?: Array<{ key: string; label: string; ours: number; cdu: number | null; delta: number | null; status: string }>
  securities?: SecLine[]
  repos?: RepoLine[]
  cash?: { ours: number; cdu: number; delta: number; status: string; cdu_lines: Array<{ currency: string; account: string | null; amount: number }>; ours_opening: { label: string; total: number }; ours_movements: number }
  receivables?: { ours: number; cdu: number | null; ours_lines: Array<{ counterparty: string; balance_kzt: number; record_date: string }>; cdu_lines: Array<{ name: string; amount_kzt: number; record_date: string | null }> }
  liabilities?: { lines: Array<{ name: string; amount: number }>; total: number | null; net_assets: number | null }
  counts?: Record<string, number>
  notes?: string[]
  file_warnings?: string[]
  file?: { file_name: string; uploaded_at: string | null; uploaded_by: string | null; sheet: string | null; cdu_name_in_file: string | null }
  [k: string]: unknown
}
interface Result { id: number; cdu_id: number; cdu_name: string; recon_date: string; recon_type: string; status: string; deviation: number | null; details: Details }

// ───────────────────────── helpers ─────────────────────────

const STATUS: Record<string, { label: string; cls: string; icon: typeof CheckCircle2 }> = {
  OK: { label: 'Совпадает', cls: 'bg-emerald-50 text-emerald-800 ring-emerald-600/25', icon: CheckCircle2 },
  MATCHED: { label: 'Совпадает', cls: 'bg-emerald-50 text-emerald-800 ring-emerald-600/25', icon: CheckCircle2 },
  MISMATCH: { label: 'Расхождения', cls: 'bg-red-50 text-red-800 ring-red-600/25', icon: XCircle },
  PENDING: { label: 'Нет данных', cls: 'bg-slate-100 text-slate-600 ring-slate-500/20', icon: Clock },
  ERROR: { label: 'Ошибка', cls: 'bg-amber-50 text-amber-800 ring-amber-600/25', icon: AlertTriangle },
}

const LINE_STATUS: Record<string, { label: string; cls: string }> = {
  OK: { label: 'совпадает', cls: 'text-emerald-700' },
  DIFF: { label: 'расхождение', cls: 'font-semibold text-red-700' },
  ONLY_OURS: { label: 'только у нас', cls: 'font-semibold text-amber-700' },
  ONLY_CDU: { label: 'только у ЧДУ', cls: 'font-semibold text-amber-700' },
  CLOSED: { label: 'закрыта на дату', cls: 'text-slate-500' },
  MISSING: { label: 'нет в файле', cls: 'text-slate-500' },
}

function StatusChip({ status, small }: { status: string; small?: boolean }) {
  const s = STATUS[status] ?? STATUS.ERROR
  const Icon = s.icon
  return (
    <span className={clsx('inline-flex items-center gap-1 rounded-md font-semibold ring-1 ring-inset', s.cls,
      small ? 'px-1.5 py-0.5 text-[11px]' : 'px-2 py-0.5 text-xs')}>
      <Icon className="h-3 w-3" /> {s.label}
    </span>
  )
}

const n2 = (v: number | null | undefined) => (v == null ? '—' : formatNumber(v, 2))
const n0 = (v: number | null | undefined) => (v == null ? '—' : formatNumber(v, 0))
const n4 = (v: number | null | undefined) => (v == null ? '—' : formatNumber(v, 4))

function Delta({ v }: { v: number | null | undefined }) {
  if (v == null) return <span className="text-slate-400">—</span>
  if (Math.abs(v) <= 1) return <span className="text-slate-500">0</span>
  return <span className={clsx('font-semibold', v > 0 ? 'text-amber-700' : 'text-red-700')}>{v > 0 ? '+' : ''}{formatNumber(v, 2)}</span>
}

// ───────────────────────── page ─────────────────────────

export default function ReconciliationPage() {
  const [searchParams] = useSearchParams()
  const qc = useQueryClient()
  const can = useAuthStore((s) => s.can)
  const workDate = useWorkContextStore((s) => s.workDate)
  const setWorkDate = useWorkContextStore((s) => s.setWorkDate)
  const linkedDate = searchParams.get('date')
  useEffect(() => {
    if (linkedDate && linkedDate !== workDate) setWorkDate(linkedDate)
  }, [linkedDate, setWorkDate, workDate])
  const [openId, setOpenId] = useState<number | null>(null)

  const ov = useQuery<Overview>({
    queryKey: ['reconciliation', 'overview', workDate],
    queryFn: async () => (await api.get('/reconciliation/overview', { params: { recon_date: workDate } })).data,
  })
  const cdus = useQuery<CDU[]>({ queryKey: ['cdus'], queryFn: async () => (await api.get('/settings/cdus')).data })

  const runAll = useMutation({
    mutationFn: async () => (await api.post('/reconciliation/run-all', null, { params: { recon_date: workDate }, timeout: 300_000 })).data,
    onSuccess: () => { toast.success('Сверка выполнена; результаты и расхождения обновлены.'); qc.invalidateQueries({ queryKey: ['reconciliation'] }) },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось выполнить сверку')),
  })

  const main = ov.data?.types.find((t) => t.main)?.code ?? 'rr_vs_holdings'
  const others = ov.data?.types.filter((t) => !t.main) ?? []
  const rows = ov.data?.rows ?? []
  const stats = useMemo(() => {
    const cells = rows.map((r) => r.results[main]).filter(Boolean)
    return {
      files: rows.filter((r) => r.file).length,
      ok: cells.filter((c) => c.status === 'OK').length,
      bad: cells.filter((c) => c.status === 'MISMATCH').length,
    }
  }, [rows, main])

  return (
    <div className="space-y-4">
      <PageHeader
        icon={GitCompare}
        title="Сверка с ЧДУ"
        subtitle="Наш расчёт портфеля на дату ↔ файл сверки, присланный управляющим: по каждой бумаге, сделке РЕПО, деньгам и итогам"
        actions={
          <>
            <Link to="/documents" className="btn-secondary h-10"><UploadCloud className="h-4 w-4" /> Загрузить файлы сверки</Link>
            {can('reconciliation.run') && (
              <button className="btn-primary h-10" onClick={() => runAll.mutate()} disabled={runAll.isPending}>
                <RefreshCw className={clsx('h-4 w-4', runAll.isPending && 'animate-spin')} /> Сверить за {formatDate(workDate)}
              </button>
            )}
          </>
        }
      />

      {!!ov.data?.file_dates.length && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
          <span>Файлы сверки загружены за:</span>
          {ov.data.file_dates.map((d) => (
            <button key={d} onClick={() => setWorkDate(d)}
              className={clsx('rounded-md px-2 py-0.5 font-semibold ring-1 ring-inset',
                d === workDate ? 'bg-emerald-600 text-white ring-emerald-600' : 'bg-white text-slate-700 ring-slate-300 hover:bg-emerald-50')}>
              {formatDate(d)}
            </button>
          ))}
        </div>
      )}

      {!!ov.data?.unbound_files.length && (
        <UnboundFiles files={ov.data.unbound_files} cdus={cdus.data ?? []} onBound={() => qc.invalidateQueries({ queryKey: ['reconciliation'] })} />
      )}

      <div className="overflow-hidden rounded-lg border border-slate-300 bg-white">
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-slate-50 px-3 py-2 text-sm">
          <span className="font-semibold text-slate-800">На {formatDate(workDate)}</span>
          <span className="text-slate-600">файлов сверки: {stats.files}</span>
          <span className="text-emerald-700">совпадает: {stats.ok}</span>
          <span className="text-red-700">с расхождениями: {stats.bad}</span>
          {ov.isFetching && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
        </div>
        <div className="overflow-x-auto">
          <table className="detail-table">
            <thead>
              <tr>
                <th>ЧДУ / портфель</th>
                <th>Файл сверки ЧДУ</th>
                <th>Наш расчёт ↔ файл ЧДУ</th>
                <th className="num">Наш расчёт, ₸</th>
                <th className="num">Файл ЧДУ, ₸</th>
                <th className="num">Разница</th>
                {others.map((t) => <th key={t.code}>{t.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const c = r.results[main]
                return (
                  <tr key={r.cdu_id} className={clsx(c && 'cursor-pointer', openId === c?.id && '[&>td]:!bg-emerald-50')}
                    onClick={() => c && setOpenId(c.id === openId ? null : c.id)}>
                    <td className="font-semibold">{r.cdu_name}</td>
                    <td className="text-xs">
                      {r.file ? <span className="inline-flex items-center gap-1"><FileSpreadsheet className="h-3.5 w-3.5 text-emerald-600" />{r.file.file_name}</span>
                        : <span className="text-slate-400">не загружен</span>}
                    </td>
                    <td>
                      {c ? (
                        <div className="flex flex-col gap-0.5">
                          <StatusChip status={c.status} small />
                          {c.counts && (c.counts.securities_diff + c.counts.repos_diff > 0) && (
                            <span className="text-[11px] text-red-700">
                              бумаг: {c.counts.securities_diff}, РЕПО: {c.counts.repos_diff}
                            </span>
                          )}
                          {c.status === 'PENDING' && c.note && <span className="text-[11px] text-slate-500">{c.note}</span>}
                        </div>
                      ) : <span className="text-[11px] text-slate-400">не запускалась</span>}
                    </td>
                    <td className="num">{n2(c?.expected)}</td>
                    <td className="num">{n2(c?.actual)}</td>
                    <td className="num"><Delta v={c?.deviation} /></td>
                    {others.map((t) => {
                      const o = r.results[t.code]
                      return (
                        <td key={t.code} onClick={(e) => { if (o) { e.stopPropagation(); setOpenId(o.id === openId ? null : o.id) } }}>
                          {o ? <StatusChip status={o.status} small /> : <span className="text-[11px] text-slate-400">—</span>}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
              {!rows.length && <tr><td colSpan={6 + others.length} className="py-8 text-center text-slate-500">Нет активных ЧДУ</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="border-t border-slate-200 px-3 py-1.5 text-xs text-slate-500">
          Щёлкните по строке, чтобы открыть построчную сверку. Сверка запускается автоматически при загрузке файла ЧДУ;
          после новых операций нажмите «Сверить за дату».
        </div>
      </div>

      {openId && <ResultPanel id={openId} onClose={() => setOpenId(null)} />}
    </div>
  )
}

// ───────────────────────── unbound files ─────────────────────────

function UnboundFiles({ files, cdus, onBound }: { files: Overview['unbound_files']; cdus: CDU[]; onBound: () => void }) {
  const [choice, setChoice] = useState<Record<number, { cdu_id?: string; doc_date?: string }>>({})
  const bind = useMutation({
    mutationFn: async (doc_id: number) => (await api.put(`/primary-data/documents/${doc_id}`, {
      cdu_id: choice[doc_id]?.cdu_id ? Number(choice[doc_id].cdu_id) : undefined,
      doc_date: choice[doc_id]?.doc_date || undefined,
    })).data,
    onSuccess: (r) => { toast.success(notificationText(r.message, 'Файл привязан к выбранному ЧДУ и дате')); onBound() },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось привязать файл к ЧДУ и дате')),
  })
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50/60 p-3">
      <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-amber-900">
        <AlertTriangle className="h-4 w-4" /> Файлы сверки без ЧДУ или даты — укажите их, и сверка выполнится сразу
      </div>
      <div className="space-y-1.5">
        {files.map((f) => (
          <div key={f.doc_id} className="flex flex-wrap items-center gap-2 text-sm">
            <FileSpreadsheet className="h-4 w-4 text-emerald-700" />
            <span className="font-medium">{f.file_name}</span>
            {f.cdu_name_in_file && <span className="text-xs text-slate-600">в файле: «{f.cdu_name_in_file}»</span>}
            <select className="input-sm w-48" value={choice[f.doc_id]?.cdu_id ?? ''}
              onChange={(e) => setChoice((c) => ({ ...c, [f.doc_id]: { ...c[f.doc_id], cdu_id: e.target.value } }))}>
              <option value="">— ЧДУ —</option>
              {cdus.map((c) => <option key={c.id} value={c.id}>{c.short_name || c.name}</option>)}
            </select>
            {!f.doc_date && (
              <input type="date" className="input-sm w-40" value={choice[f.doc_id]?.doc_date ?? ''}
                onChange={(e) => setChoice((c) => ({ ...c, [f.doc_id]: { ...c[f.doc_id], doc_date: e.target.value } }))} />
            )}
            <button className="btn-primary h-8 px-3 text-xs" disabled={bind.isPending || (!choice[f.doc_id]?.cdu_id && !choice[f.doc_id]?.doc_date)}
              onClick={() => bind.mutate(f.doc_id)}>
              <Link2 className="h-3.5 w-3.5" /> Привязать
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ───────────────────────── result panel ─────────────────────────

function ResultPanel({ id, onClose }: { id: number; onClose: () => void }) {
  const qc = useQueryClient()
  const can = useAuthStore((s) => s.can)
  const q = useQuery<Result>({ queryKey: ['reconciliation', 'result', id], queryFn: async () => (await api.get(`/reconciliation/result/${id}`)).data })
  const rerun = useMutation({
    mutationFn: async () => (await api.post('/reconciliation/run', {
      cdu_id: q.data!.cdu_id, recon_date: q.data!.recon_date, recon_type: q.data!.recon_type,
    })).data,
    onSuccess: () => { toast.success('Сверка повторно выполнена; результаты обновлены.'); qc.invalidateQueries({ queryKey: ['reconciliation'] }) },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось повторно выполнить сверку')),
  })
  const exportXlsx = async () => {
    try {
      const resp = await api.get(`/reconciliation/result/${id}/export`, { responseType: 'blob' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(resp.data)
      a.download = `Сверка_${q.data?.cdu_name ?? ''}_${q.data?.recon_date ?? ''}.xlsx`
      a.click()
      URL.revokeObjectURL(a.href)
      toast.success(`Сверка ${q.data?.cdu_name ?? ''} за ${formatDate(q.data?.recon_date ?? '')} скачана в формате XLSX.`)
    } catch (error) {
      toast.error(apiErrorMessage(error, `Не удалось скачать сверку ${q.data?.cdu_name ?? ''} за ${formatDate(q.data?.recon_date ?? '')}`))
    }
  }

  if (q.isLoading || !q.data) {
    return <div className="flex items-center gap-2 rounded-lg border border-slate-300 bg-white p-4 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Загрузка…</div>
  }
  const r = q.data
  const d = r.details
  const lineByLine = r.recon_type === 'rr_vs_holdings' && !!d.summary
  return (
    <section className="overflow-hidden rounded-lg border border-slate-300 bg-white">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-300 bg-slate-50 px-3 py-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-bold text-slate-900">{r.cdu_name} — сверка на {formatDate(r.recon_date)}</h2>
            <StatusChip status={r.status} />
          </div>
          {d.file && (
            <div className="text-xs text-slate-600">
              Файл ЧДУ: <b>{d.file.file_name}</b>{d.file.sheet ? ` (лист «${d.file.sheet}»)` : ''} · загружен {formatDate(d.file.uploaded_at)} {d.file.uploaded_by ?? ''}
            </div>
          )}
        </div>
        {can('reconciliation.run') && (
          <button className="btn-secondary h-8 px-3 text-xs" onClick={() => rerun.mutate()} disabled={rerun.isPending}>
            <RefreshCw className={clsx('h-3.5 w-3.5', rerun.isPending && 'animate-spin')} /> Сверить заново
          </button>
        )}
        {lineByLine && (
          <button className="btn-secondary h-8 px-3 text-xs" onClick={exportXlsx}><Download className="h-3.5 w-3.5" /> Excel для ЧДУ</button>
        )}
        <button className="rounded p-1 text-slate-500 hover:bg-slate-200" onClick={onClose} aria-label="Закрыть"><X className="h-4 w-4" /></button>
      </div>
      <div className="space-y-3 p-3">
        {d.note && <div className="rounded-md bg-slate-100 px-3 py-2 text-sm text-slate-700">{d.note}</div>}
        {lineByLine ? <LineByLine d={d} /> : <GenericDetails d={d} />}
      </div>
    </section>
  )
}

function LineByLine({ d }: { d: Details }) {
  const [tab, setTab] = useState<'sec' | 'repo' | 'cash' | 'liab'>('sec')
  const [onlyDiff, setOnlyDiff] = useState(d.status !== 'OK')
  const secs = (d.securities ?? []).filter((s) => !onlyDiff || s.status !== 'OK')
  const repos = (d.repos ?? []).filter((s) => !onlyDiff || !['OK', 'CLOSED'].includes(s.status))
  const secBad = (d.securities ?? []).filter((s) => s.status !== 'OK').length
  const repoBad = (d.repos ?? []).filter((s) => !['OK', 'CLOSED'].includes(s.status)).length
  const tabs = [
    { id: 'sec' as const, label: `Ценные бумаги (${d.securities?.length ?? 0})`, bad: secBad },
    { id: 'repo' as const, label: `Обратное РЕПО (${d.repos?.length ?? 0})`, bad: repoBad },
    { id: 'cash' as const, label: 'Деньги и дебиторка', bad: (d.cash?.status === 'OK' ? 0 : 1) },
    { id: 'liab' as const, label: 'Комиссии ЧДУ', bad: 0 },
  ]
  return (
    <>
      <div className="overflow-x-auto rounded-md border border-slate-300">
        <table className="detail-table">
          <thead><tr><th>Раздел</th><th className="num">Наш расчёт, ₸</th><th className="num">Файл ЧДУ, ₸</th><th className="num">Разница, ₸</th><th>Статус</th></tr></thead>
          <tbody>
            {(d.summary ?? []).map((s) => (
              <tr key={s.key} className={clsx(s.key === 'total' && '[&>td]:!bg-slate-100 [&>td]:font-bold')}>
                <td>{s.label}</td><td className="num">{n2(s.ours)}</td><td className="num">{n2(s.cdu)}</td>
                <td className="num"><Delta v={s.delta} /></td>
                <td className={LINE_STATUS[s.status]?.cls}>{LINE_STATUS[s.status]?.label ?? processStatusLabel(s.status)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(d.notes?.length || d.file_warnings?.length) ? (
        <ul className="space-y-0.5 text-xs text-slate-600">
          {d.notes?.map((n) => <li key={n} className="flex gap-1.5"><Info className="mt-0.5 h-3 w-3 shrink-0" />{n}</li>)}
          {d.file_warnings?.map((n) => <li key={n} className="flex gap-1.5 text-amber-800"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />Файл ЧДУ: {n}</li>)}
        </ul>
      ) : null}

      <div className="flex flex-wrap items-center gap-1 border-b border-slate-200">
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={clsx('-mb-px border-b-2 px-3 py-1.5 text-sm font-semibold',
              tab === t.id ? 'border-emerald-600 text-emerald-800' : 'border-transparent text-slate-600 hover:text-slate-900')}>
            {t.label}{t.bad > 0 && <span className="ml-1.5 rounded bg-red-100 px-1.5 text-[11px] text-red-700">{t.bad}</span>}
          </button>
        ))}
        {(tab === 'sec' || tab === 'repo') && (
          <label className="ml-auto flex items-center gap-1.5 text-xs text-slate-700">
            <input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} className="h-3.5 w-3.5" />
            только расхождения
          </label>
        )}
      </div>

      {tab === 'sec' && <SecTable rows={secs} />}
      {tab === 'repo' && <RepoTable rows={repos} />}
      {tab === 'cash' && <CashTab d={d} />}
      {tab === 'liab' && <LiabTab d={d} />}
    </>
  )
}

function Pair({ cdu, ours, bad, fmt }: { cdu: number | null | undefined; ours: number | null | undefined; bad: boolean; fmt: (v: number | null | undefined) => string }) {
  return (
    <>
      <td className="num">{fmt(cdu)}</td>
      <td className={clsx('num', bad && '!bg-red-50 font-semibold text-red-800')}>{fmt(ours)}</td>
    </>
  )
}

function SecTable({ rows }: { rows: SecLine[] }) {
  if (!rows.length) return <div className="py-6 text-center text-sm text-emerald-700">Расхождений по бумагам нет</div>
  return (
    <div className="max-h-[60vh] overflow-auto rounded-md border border-slate-300">
      <table className="detail-table">
        <thead className="sticky top-0 z-10">
          <tr>
            <th rowSpan={2}>Бумага</th>
            <th colSpan={2} className="text-center">Количество</th>
            <th colSpan={2} className="text-center">Цена, %</th>
            <th colSpan={2} className="text-center">НКД, ₸</th>
            <th colSpan={2} className="text-center">Стоимость, ₸</th>
            <th rowSpan={2} className="num">Разница, ₸</th>
            <th rowSpan={2}>Статус</th>
          </tr>
          <tr><th>ЧДУ</th><th>наш</th><th>ЧДУ</th><th>наш</th><th>ЧДУ</th><th>наш</th><th>ЧДУ</th><th>наш</th></tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <Fragment key={s.isin}>
              <tr>
                <td>
                  <div className="font-mono text-xs font-semibold">{s.isin}</div>
                  <div className="max-w-[16rem] truncate text-[11px] text-slate-500" title={s.name ?? ''}>{[s.ticker, s.name].filter(Boolean).join(' · ')}</div>
                  {(s.ours?.lots ?? 0) + (s.cdu?.lots ?? 0) > 2 && (
                    <div className="text-[10px] text-slate-400">лотов: ЧДУ {s.cdu?.lots ?? 0}, наших {s.ours?.lots ?? 0}</div>
                  )}
                </td>
                <Pair cdu={s.cdu?.quantity} ours={s.ours?.quantity} bad={s.fields.includes('quantity')} fmt={n0} />
                <Pair cdu={s.cdu?.price} ours={s.ours?.price} bad={s.fields.includes('price')} fmt={n4} />
                <Pair cdu={s.cdu?.accrued} ours={s.ours?.accrued} bad={s.fields.includes('accrued')} fmt={n2} />
                <Pair cdu={s.cdu?.value} ours={s.ours?.value} bad={s.fields.includes('value')} fmt={n2} />
                <td className="num"><Delta v={s.delta_value} /></td>
                <td className={clsx('whitespace-nowrap text-xs', LINE_STATUS[s.status]?.cls)}>
                  {LINE_STATUS[s.status]?.label}
                  {s.status === 'OK' && s.ours?.price_source && <div className="text-[10px] font-normal text-slate-400">цена: {sourceLabel(s.ours.price_source)}</div>}
                </td>
              </tr>
              {s.status !== 'OK' && s.reasons.length > 0 && (
                <tr className="[&>td]:!bg-red-50/40">
                  <td colSpan={11} className="text-xs text-slate-800">
                    {s.reasons.map((x) => <div key={x}>• {x}</div>)}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RepoTable({ rows }: { rows: RepoLine[] }) {
  if (!rows.length) return <div className="py-6 text-center text-sm text-emerald-700">Расхождений по РЕПО нет</div>
  return (
    <div className="max-h-[60vh] overflow-auto rounded-md border border-slate-300">
      <table className="detail-table">
        <thead className="sticky top-0 z-10">
          <tr>
            <th rowSpan={2}>Залог / сделка</th>
            <th rowSpan={2}>Открытие → закрытие</th>
            <th colSpan={2} className="text-center">Сумма открытия, ₸</th>
            <th colSpan={2} className="text-center">Вознаграждение, ₸</th>
            <th colSpan={2} className="text-center">Стоимость на дату, ₸</th>
            <th rowSpan={2} className="num">Разница</th>
            <th rowSpan={2}>Статус</th>
          </tr>
          <tr><th>ЧДУ</th><th>наша</th><th>ЧДУ</th><th>наше</th><th>ЧДУ</th><th>наша</th></tr>
        </thead>
        <tbody>
          {rows.map((s, i) => {
            const any = s.cdu ?? s.ours
            return (
              <Fragment key={i}>
                <tr className={clsx(s.status === 'CLOSED' && 'text-slate-500')}>
                  <td>
                    <div className="font-mono text-xs font-semibold">{s.isin ?? '—'}</div>
                    {s.ours?.deal_id && <div className="text-[11px] text-slate-500">сделка {s.ours.deal_id}</div>}
                  </td>
                  <td className="whitespace-nowrap text-xs">{formatDate(any?.open_date)} → {formatDate(any?.close_date)}</td>
                  <Pair cdu={s.cdu?.open_amount} ours={s.ours?.open_amount} bad={false} fmt={n2} />
                  <Pair cdu={s.cdu?.accrued} ours={s.ours?.accrued} bad={s.fields.includes('accrued')} fmt={n2} />
                  <Pair cdu={s.cdu ? s.cdu.value_effective : null} ours={s.ours?.value} bad={s.fields.includes('value')} fmt={n2} />
                  <td className="num"><Delta v={s.delta_value} /></td>
                  <td className={clsx('whitespace-nowrap text-xs', LINE_STATUS[s.status]?.cls)}>{LINE_STATUS[s.status]?.label}</td>
                </tr>
                {!['OK'].includes(s.status) && s.reasons.length > 0 && (
                  <tr className={clsx(s.status !== 'CLOSED' && '[&>td]:!bg-red-50/40')}>
                    <td colSpan={10} className="text-xs text-slate-700">{s.reasons.map((x) => <div key={x}>• {x}</div>)}</td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function CashTab({ d }: { d: Details }) {
  const c = d.cash
  const r = d.receivables
  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      {c && (
        <div className="rounded-md border border-slate-300">
          <div className="border-b border-slate-200 bg-slate-100 px-3 py-1.5 text-xs font-semibold uppercase text-slate-600">Деньги на счетах</div>
          <table className="detail-table">
            <tbody>
              <tr><td>По файлу ЧДУ</td><td className="num">{n2(c.cdu)}</td></tr>
              {c.cdu_lines.map((l, i) => <tr key={i}><td className="pl-5 text-xs text-slate-600">{l.currency}{l.account ? ` · ${l.account}` : ''}</td><td className="num text-xs">{n2(l.amount)}</td></tr>)}
              <tr><td>Наш расчёт</td><td className="num">{n2(c.ours)}</td></tr>
              <tr><td className="pl-5 text-xs text-slate-600">{c.ours_opening?.label}: {n2(c.ours_opening?.total)}; движений после: {c.ours_movements}</td><td /></tr>
              <tr className="[&>td]:!bg-slate-100 [&>td]:font-bold"><td>Разница</td><td className="num"><Delta v={c.delta} /></td></tr>
            </tbody>
          </table>
        </div>
      )}
      {r && (
        <div className="rounded-md border border-slate-300">
          <div className="border-b border-slate-200 bg-slate-100 px-3 py-1.5 text-xs font-semibold uppercase text-slate-600">Дебиторская задолженность</div>
          <table className="detail-table">
            <tbody>
              <tr><td>По файлу ЧДУ</td><td className="num">{n2(r.cdu)}</td></tr>
              {r.cdu_lines.map((l, i) => <tr key={`c${i}`}><td className="pl-5 text-xs text-slate-600">{l.name}</td><td className="num text-xs">{n2(l.amount_kzt)}</td></tr>)}
              <tr><td>Наш расчёт</td><td className="num">{n2(r.ours)}</td></tr>
              {r.ours_lines.map((l, i) => <tr key={`o${i}`}><td className="pl-5 text-xs text-slate-600">{l.counterparty} · {formatDate(l.record_date)}</td><td className="num text-xs">{n2(l.balance_kzt)}</td></tr>)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function LiabTab({ d }: { d: Details }) {
  const l = d.liabilities
  if (!l?.lines.length) return <div className="py-4 text-sm text-slate-500">В файле ЧДУ нет кредиторской задолженности и комиссий</div>
  return (
    <div className="max-w-xl rounded-md border border-slate-300">
      <table className="detail-table">
        <tbody>
          {l.lines.map((x) => <tr key={x.name}><td>{x.name}</td><td className="num">{n2(x.amount)}</td></tr>)}
          <tr className="[&>td]:!bg-slate-100 [&>td]:font-bold"><td>Итого кредиторская задолженность</td><td className="num">{n2(l.total)}</td></tr>
          {l.net_assets != null && <tr><td>Итого чистых активов (по файлу)</td><td className="num">{n2(l.net_assets)}</td></tr>}
        </tbody>
      </table>
      <div className="px-3 py-1.5 text-xs text-slate-500">Комиссии ЧДУ в системе не ведутся — показаны для информации, в сверку активов не входят.</div>
    </div>
  )
}

function GenericDetails({ d }: { d: Details }) {
  const items = (d.items as Array<Record<string, unknown>> | undefined) ?? []
  const skip = new Set(['note', 'items', 'status'])
  const plain = Object.entries(d).filter(([k, v]) => !skip.has(k) && (typeof v === 'number' || typeof v === 'string'))
  return (
    <div className="space-y-2">
      {!!plain.length && (
        <table className="detail-table max-w-xl"><tbody>
          {plain.map(([k, v]) => <tr key={k}><td className="text-slate-600">{fieldLabel(k)}</td><td className="num">{typeof v === 'number' ? n2(v) : String(v)}</td></tr>)}
        </tbody></table>
      )}
      {!!items.length && (
        <div className="overflow-x-auto rounded-md border border-slate-300">
          <table className="detail-table">
            <thead><tr>{Object.keys(items[0]).map((k) => <th key={k}>{fieldLabel(k)}</th>)}</tr></thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={i}>{Object.entries(it).map(([k, v]) => <Fragment key={k}><td className={typeof v === 'number' ? 'num' : ''}>{typeof v === 'number' ? n2(v) : String(v ?? '—')}</td></Fragment>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
