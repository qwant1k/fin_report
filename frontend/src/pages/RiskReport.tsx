import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Calendar,
  FileText,
  MessageSquarePlus,
  Pencil,
  ShieldAlert,
  Trash2,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { CDU } from '@/lib/types'
import { useAuthStore } from '@/lib/auth'

// ─────────────── types ───────────────

interface RrDate {
  report_date: string
  rows: number
  total_value: number
}

interface RrSummary {
  id: number
  cdu_id: number
  cdu_name: string | null
  total_mv_prev: number | null
  total_mv_current: number | null
  total_daily_change: number | null
  cdu_share_pct: number | null
  ytm_weighted: number | null
  duration_weighted: number | null
  benchmark_duration: number | null
  duration_status: string | null
}

interface RrPosition {
  id: number
  cdu_id: number
  cdu_name: string | null
  instrument_code: string | null
  instrument_name: string | null
  category: string | null
  nominal_volume: number | null
  current_price: number | null
  accrued_interest: number | null
  market_value_current: number | null
  market_value_prev: number | null
  daily_change: number | null
  pct_of_total: number | null
  ytm: number | null
  duration: number | null
}

interface RrCash {
  id: number
  cdu_id: number
  cdu_name: string | null
  currency: string
  amount: number
  portfolio_code: string | null
}

interface RrNote {
  id: number
  report_date: string
  cdu_id: number | null
  section: string
  field_key: string
  override_value: unknown
  comment: string | null
  version: number
  created_by: string | null
  created_at: string | null
  updated_by: string | null
  updated_at: string | null
}

interface Snapshot {
  report_date: string
  cdu_id: number | null
  summary: RrSummary[]
  positions: RrPosition[]
  cash: RrCash[]
  notes: RrNote[]
}

const SECTION_LABEL: Record<string, string> = {
  summary: 'Сводка',
  positions: 'Позиции',
  cash: 'Денежные средства',
  stress: 'Стресс-тест',
  other: 'Прочее',
}

const SECTION_COLOR: Record<string, string> = {
  summary:   'bg-emerald-100 text-emerald-800 ring-emerald-200',
  positions: 'bg-cyan-100 text-cyan-800 ring-cyan-200',
  cash:      'bg-blue-100 text-blue-800 ring-blue-200',
  stress:    'bg-amber-100 text-amber-800 ring-amber-200',
  other:     'bg-slate-100 text-slate-700 ring-slate-200',
}

function fmt(n: number | null | undefined, digits = 2): string {
  if (n == null) return '—'
  return new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n)
}

function fmtMln(n: number | null | undefined): string {
  return n == null ? '—' : fmt(n / 1_000_000, 1) + ' млн'
}

// ─────────────── page ───────────────

export default function RiskReportPage() {
  const qc = useQueryClient()
  const canWrite = useAuthStore((s) => s.can('risk_report.notes.edit'))

  const datesQ = useQuery<RrDate[]>({
    queryKey: ['rr-dates'],
    queryFn: async () => (await api.get('/risk-report/dates')).data,
  })

  const cdusQ = useQuery<CDU[]>({
    queryKey: ['cdus'],
    queryFn: async () => (await api.get('/settings/cdus')).data,
  })

  const [selectedDate, setSelectedDate] = useState<string>('')
  const [cduFilter, setCduFilter] = useState<number | ''>('')
  const [tab, setTab] = useState<'overview' | 'positions' | 'cash' | 'notes'>('overview')
  const [noteModal, setNoteModal] = useState<RrNote | 'new' | null>(null)

  // Auto-select the most recent date when the list loads.
  const effectiveDate = selectedDate || datesQ.data?.[0]?.report_date || ''

  const snapQ = useQuery<Snapshot>({
    queryKey: ['rr-snapshot', effectiveDate, cduFilter],
    queryFn: async () => {
      const params: Record<string, unknown> = { report_date: effectiveDate }
      if (cduFilter) params.cdu_id = cduFilter
      return (await api.get('/risk-report/snapshot', { params })).data
    },
    enabled: !!effectiveDate,
  })

  const removeNote = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/risk-report/notes/${id}`)).data,
    onSuccess: () => {
      toast.success('Заметка удалена')
      qc.invalidateQueries({ queryKey: ['rr-snapshot'] })
    },
    onError: () => toast.error('Не удалось удалить'),
  })

  const summary = snapQ.data?.summary ?? []
  const positions = snapQ.data?.positions ?? []
  const cash = snapQ.data?.cash ?? []
  const notes = snapQ.data?.notes ?? []

  const totals = useMemo(() => {
    const totalMV = summary.reduce((s, x) => s + (x.total_mv_current ?? 0), 0)
    const totalChg = summary.reduce((s, x) => s + (x.total_daily_change ?? 0), 0)
    return { totalMV, totalChg }
  }, [summary])

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <ShieldAlert className="h-6 w-6 text-emerald-600" />
            Risk Report
          </h1>
          <p className="text-sm text-slate-500">
            Просмотр импортированных данных риск-отчёта и ручные дополнения / комментарии.
          </p>
        </div>
      </header>

      {/* ── Date + CDU selectors ── */}
      <div className="card p-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div>
            <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-slate-600">
              <Calendar className="h-3.5 w-3.5" /> Отчётная дата
            </label>
            <select
              className="input"
              value={effectiveDate}
              onChange={(e) => setSelectedDate(e.target.value)}
            >
              {(datesQ.data ?? []).map((d) => (
                <option key={d.report_date} value={d.report_date}>
                  {d.report_date} · {d.rows} строк · {fmtMln(d.total_value)}
                </option>
              ))}
              {datesQ.data?.length === 0 && <option value="">Нет данных</option>}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">ЧДУ</label>
            <select
              className="input"
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
          </div>
          <div className="flex items-end justify-end">
            {canWrite && effectiveDate && (
              <button
                onClick={() => setNoteModal('new')}
                className="btn-primary"
              >
                <MessageSquarePlus className="h-4 w-4" />
                Добавить заметку
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── KPI strip ── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Kpi label="Дата отчёта" value={effectiveDate || '—'} />
        <Kpi label="ЧДУ в отчёте" value={summary.length} />
        <Kpi label="Стоимость портфеля" value={fmtMln(totals.totalMV)} highlight />
        <Kpi
          label="Изменение за день"
          value={fmtMln(totals.totalChg)}
          tone={totals.totalChg < 0 ? 'down' : totals.totalChg > 0 ? 'up' : 'flat'}
        />
      </div>

      {/* ── Tabs ── */}
      <div className="card overflow-hidden">
        <div className="flex border-b border-slate-200">
          {([
            ['overview',  'Сводка',     summary.length],
            ['positions', 'Позиции',    positions.length],
            ['cash',      'Денежные средства', cash.length],
            ['notes',     'Заметки',    notes.length],
          ] as const).map(([key, label, count]) => (
            <button
              key={key}
              onClick={() => setTab(key as any)}
              className={`px-4 py-2 text-sm font-medium transition ${
                tab === key
                  ? 'border-b-2 border-emerald-600 text-emerald-700'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              {label}
              <span className="ml-1.5 text-xs text-slate-400">({count})</span>
            </button>
          ))}
        </div>

        <div className="p-0">
          {snapQ.isLoading && (
            <div className="p-10 text-center text-slate-400">Загрузка…</div>
          )}
          {!snapQ.isLoading && tab === 'overview' && <SummaryTab rows={summary} />}
          {!snapQ.isLoading && tab === 'positions' && <PositionsTab rows={positions} />}
          {!snapQ.isLoading && tab === 'cash' && <CashTab rows={cash} />}
          {!snapQ.isLoading && tab === 'notes' && (
            <NotesTab
              rows={notes}
              canWrite={canWrite}
              onEdit={(n) => setNoteModal(n)}
              onDelete={(id) => {
                if (confirm('Удалить заметку?')) removeNote.mutate(id)
              }}
            />
          )}
        </div>
      </div>

      {/* ── Note modal ── */}
      {noteModal && effectiveDate && (
        <NoteModal
          existing={noteModal === 'new' ? null : noteModal}
          reportDate={effectiveDate}
          cdus={cdusQ.data ?? []}
          onClose={() => setNoteModal(null)}
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ['rr-snapshot'] })
            setNoteModal(null)
          }}
        />
      )}
    </div>
  )
}

// ─────────────── KPI ───────────────

function Kpi({
  label, value, subtitle, highlight, tone,
}: {
  label: string
  value: string | number
  subtitle?: string
  highlight?: boolean
  tone?: 'up' | 'down' | 'flat'
}) {
  const toneColor =
    tone === 'down' ? 'text-red-600' : tone === 'up' ? 'text-emerald-700' : ''
  return (
    <div className={`card p-4 ${highlight ? 'border-emerald-200 bg-emerald-50/70' : ''}`}>
      <div className="text-xs font-medium uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${highlight ? 'text-emerald-700' : 'text-slate-900'} ${toneColor}`}>
        {value}
      </div>
      {subtitle && <div className="mt-0.5 text-xs text-slate-500">{subtitle}</div>}
    </div>
  )
}

// ─────────────── Summary tab ───────────────

function SummaryTab({ rows }: { rows: RrSummary[] }) {
  if (rows.length === 0) {
    return <div className="p-10 text-center text-slate-400">Нет данных по сводке на эту дату</div>
  }
  return (
    <div className="table-wrap">
      <table className="kdif-table">
        <thead>
          <tr>
            <th>ЧДУ</th>
            <th className="text-right">Стоимость (T)</th>
            <th className="text-right">Стоимость (T-1)</th>
            <th className="text-right">Изм. за день</th>
            <th className="text-right">Доля</th>
            <th className="text-right">YTM</th>
            <th className="text-right">Duration</th>
            <th>Статус</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="font-semibold">{r.cdu_name ?? `#${r.cdu_id}`}</td>
              <td className="text-right font-mono font-semibold">{fmtMln(r.total_mv_current)}</td>
              <td className="text-right font-mono text-slate-500">{fmtMln(r.total_mv_prev)}</td>
              <td
                className={`text-right font-mono ${
                  (r.total_daily_change ?? 0) < 0
                    ? 'text-red-600'
                    : (r.total_daily_change ?? 0) > 0
                      ? 'text-emerald-700'
                      : 'text-slate-500'
                }`}
              >
                {fmtMln(r.total_daily_change)}
              </td>
              <td className="text-right font-mono">{fmt(r.cdu_share_pct, 2)} %</td>
              <td className="text-right font-mono">{fmt(r.ytm_weighted, 2)} %</td>
              <td className="text-right font-mono">{fmt(r.duration_weighted, 2)}</td>
              <td>
                {r.duration_status && (
                  <span
                    className={`inline-flex rounded-md px-2 py-0.5 text-xs font-medium ring-1 ${
                      r.duration_status === 'OK'
                        ? 'bg-emerald-50 text-emerald-700 ring-emerald-200'
                        : 'bg-amber-50 text-amber-800 ring-amber-200'
                    }`}
                  >
                    {r.duration_status}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─────────────── Positions tab ───────────────

function PositionsTab({ rows }: { rows: RrPosition[] }) {
  if (rows.length === 0) {
    return <div className="p-10 text-center text-slate-400">Нет позиций на эту дату</div>
  }
  return (
    <div className="table-wrap">
      <table className="kdif-table">
        <thead>
          <tr>
            <th>ЧДУ</th>
            <th>Категория</th>
            <th>Тикер</th>
            <th>Название</th>
            <th className="text-right">Номинал</th>
            <th className="text-right">Цена</th>
            <th className="text-right">Стоимость</th>
            <th className="text-right">Изм.</th>
            <th className="text-right">Доля</th>
            <th className="text-right">YTM</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.id}>
              <td>{p.cdu_name ?? `#${p.cdu_id}`}</td>
              <td className="text-xs text-slate-500">{p.category ?? '—'}</td>
              <td className="font-mono text-xs">{p.instrument_code ?? '—'}</td>
              <td className="max-w-xs truncate" title={p.instrument_name ?? ''}>
                {p.instrument_name ?? '—'}
              </td>
              <td className="text-right font-mono">{fmt(p.nominal_volume, 0)}</td>
              <td className="text-right font-mono">{fmt(p.current_price, 4)}</td>
              <td className="text-right font-mono font-semibold">{fmtMln(p.market_value_current)}</td>
              <td
                className={`text-right font-mono ${
                  (p.daily_change ?? 0) < 0
                    ? 'text-red-600'
                    : (p.daily_change ?? 0) > 0
                      ? 'text-emerald-700'
                      : 'text-slate-500'
                }`}
              >
                {fmtMln(p.daily_change)}
              </td>
              <td className="text-right font-mono">{fmt(p.pct_of_total, 2)} %</td>
              <td className="text-right font-mono">{fmt(p.ytm, 2)} %</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─────────────── Cash tab ───────────────

function CashTab({ rows }: { rows: RrCash[] }) {
  if (rows.length === 0) {
    return <div className="p-10 text-center text-slate-400">Нет cash-снимков на эту дату</div>
  }
  return (
    <div className="table-wrap">
      <table className="kdif-table">
        <thead>
          <tr>
            <th>ЧДУ</th>
            <th>Валюта</th>
            <th>Портфель</th>
            <th className="text-right">Остаток</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id}>
              <td>{c.cdu_name ?? `#${c.cdu_id}`}</td>
              <td className="font-mono text-xs">{c.currency}</td>
              <td className="text-xs text-slate-500">{c.portfolio_code ?? '—'}</td>
              <td className="text-right font-mono font-semibold">{fmt(c.amount, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─────────────── Notes tab ───────────────

function NotesTab({
  rows, canWrite, onEdit, onDelete,
}: {
  rows: RrNote[]
  canWrite: boolean
  onEdit: (n: RrNote) => void
  onDelete: (id: number) => void
}) {
  if (rows.length === 0) {
    return (
      <div className="p-10 text-center text-slate-400">
        <FileText className="mx-auto mb-2 h-8 w-8 opacity-50" />
        <div>Заметок пока нет</div>
        {canWrite && (
          <div className="mt-1 text-xs">
            Используйте кнопку «Добавить заметку», чтобы добавить комментарий или оверрайд.
          </div>
        )}
      </div>
    )
  }
  return (
    <div className="divide-y divide-slate-100">
      {rows.map((n) => (
        <div key={n.id} className="p-4 hover:bg-slate-50">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`inline-flex rounded-md px-2 py-0.5 text-xs font-medium ring-1 ${
                    SECTION_COLOR[n.section] ?? SECTION_COLOR.other
                  }`}
                >
                  {SECTION_LABEL[n.section] ?? n.section}
                </span>
                <code className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
                  {n.field_key}
                </code>
                {n.cdu_id != null && (
                  <span className="text-xs text-slate-500">ЧДУ #{n.cdu_id}</span>
                )}
                <span className="text-xs text-slate-400">v{n.version}</span>
              </div>

              {n.override_value !== null && n.override_value !== undefined && (
                <div className="mt-2 rounded-md bg-amber-50 px-3 py-1.5 text-sm ring-1 ring-amber-200">
                  <span className="text-xs font-semibold text-amber-700">Оверрайд: </span>
                  <code className="text-amber-900">{JSON.stringify(n.override_value)}</code>
                </div>
              )}

              {n.comment && (
                <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">{n.comment}</p>
              )}

              <div className="mt-2 text-xs text-slate-400">
                {n.created_by ?? '—'} ·{' '}
                {n.created_at ? new Date(n.created_at).toLocaleString() : '—'}
                {n.updated_at && n.updated_at !== n.created_at && (
                  <>
                    {' · '}изменено{' '}{new Date(n.updated_at).toLocaleString()}
                    {n.updated_by && ` (${n.updated_by})`}
                  </>
                )}
              </div>
            </div>

            {canWrite && (
              <div className="flex shrink-0 gap-1">
                <button
                  onClick={() => onEdit(n)}
                  className="rounded p-1.5 text-slate-500 hover:bg-slate-100 hover:text-emerald-700"
                  title="Редактировать"
                >
                  <Pencil className="h-4 w-4" />
                </button>
                <button
                  onClick={() => onDelete(n.id)}
                  className="rounded p-1.5 text-slate-500 hover:bg-red-50 hover:text-red-600"
                  title="Удалить"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─────────────── Note modal ───────────────

function NoteModal({
  existing, reportDate, cdus, onClose, onSaved,
}: {
  existing: RrNote | null
  reportDate: string
  cdus: CDU[]
  onClose: () => void
  onSaved: () => void
}) {
  const isEdit = !!existing
  const [section, setSection] = useState(existing?.section ?? 'summary')
  const [fieldKey, setFieldKey] = useState(existing?.field_key ?? '')
  const [cduId, setCduId] = useState<number | ''>(existing?.cdu_id ?? '')
  const [override, setOverride] = useState<string>(
    existing?.override_value != null ? JSON.stringify(existing.override_value) : '',
  )
  const [comment, setComment] = useState(existing?.comment ?? '')

  const save = useMutation({
    mutationFn: async () => {
      let parsedOverride: unknown = null
      if (override.trim()) {
        try {
          parsedOverride = JSON.parse(override)
        } catch {
          parsedOverride = override.trim()  // store as string if not valid JSON
        }
      }
      const payload = {
        report_date: reportDate,
        section,
        field_key: fieldKey.trim(),
        cdu_id: cduId || null,
        override_value: parsedOverride,
        comment: comment.trim() || null,
      }
      if (isEdit) {
        return (await api.patch(`/risk-report/notes/${existing!.id}`, payload)).data
      }
      return (await api.post('/risk-report/notes', payload)).data
    },
    onSuccess: () => {
      toast.success(isEdit ? 'Заметка обновлена' : 'Заметка добавлена')
      onSaved()
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      toast.error(typeof detail === 'string' ? detail : 'Не удалось сохранить')
    },
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="card w-full max-w-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-200 p-4">
          <h2 className="text-lg font-semibold">
            {isEdit ? 'Редактирование заметки' : 'Новая заметка к Risk Report'}
          </h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-3 p-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">Раздел</label>
              <select
                className="input"
                value={section}
                onChange={(e) => setSection(e.target.value)}
              >
                {Object.entries(SECTION_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">ЧДУ (опционально)</label>
              <select
                className="input"
                value={cduId}
                onChange={(e) => setCduId(e.target.value ? Number(e.target.value) : '')}
              >
                <option value="">Все ЧДУ</option>
                {cdus.map((c) => (
                  <option key={c.id} value={c.id}>{c.short_name}</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">
              Ключ поля <span className="text-red-500">*</span>
            </label>
            <input
              className="input font-mono"
              value={fieldKey}
              onChange={(e) => setFieldKey(e.target.value)}
              placeholder="positions.KZ0001234567.market_value"
              disabled={isEdit}
            />
            <p className="mt-1 text-xs text-slate-500">
              Свободный путь, например <code>positions.&lt;ISIN&gt;.market_value</code> или{' '}
              <code>stress_test.scenario_a</code>.
            </p>
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">
              Значение-оверрайд (JSON или строка)
            </label>
            <input
              className="input font-mono"
              value={override}
              onChange={(e) => setOverride(e.target.value)}
              placeholder='1234.56 или "OK" или {"value": 1, "unit": "%"}'
            />
            <p className="mt-1 text-xs text-slate-500">
              Оставьте пустым для заметки без оверрайда.
            </p>
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">Комментарий</label>
            <textarea
              className="input min-h-[80px]"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Поясните причину оверрайда или замечание для аудита…"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-200 p-4">
          <button onClick={onClose} className="btn-secondary">Отменить</button>
          <button
            onClick={() => save.mutate()}
            disabled={save.isPending || !fieldKey.trim()}
            className="btn-primary"
          >
            {save.isPending ? 'Сохранение…' : 'Сохранить'}
          </button>
        </div>
      </div>
    </div>
  )
}
