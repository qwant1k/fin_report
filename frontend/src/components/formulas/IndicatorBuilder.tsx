import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, Archive, Bell, CheckCircle2, ChevronDown, ChevronRight, History, Loader2, Play, Plus, RotateCcw,
  Save, Search, Sparkles, XCircle,
} from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'

import { api } from '@/lib/api'
import { apiErrorMessage } from '@/lib/notifications'
import { useAuthStore } from '@/lib/auth'
import { useWorkContextStore } from '@/lib/workContext'
import { formatDate } from '@/lib/format'
import { ALERT_OPS, UNIT_LABEL, breached, formatIndicator, type IndicatorLevel, type IndicatorUnit } from '@/lib/indicators'
import { FieldChip, PrettyFormula } from './FormulaChips'

interface Indicator {
  id: number; code: string; name: string; description: string | null; level: IndicatorLevel; unit: IndicatorUnit
  expression: string; decimals: number; show_on_dashboard: boolean
  alert_op: string | null; alert_threshold: number | null; alert_severity: string | null
  status: 'ACTIVE' | 'DRAFT' | 'ARCHIVED'; version: number; pretty: string | null; valid: boolean; error: string | null
  updated_by: string | null; updated_at: string | null
}
interface Template { name: string; level: IndicatorLevel; unit: IndicatorUnit; expression: string; description: string; alert_op?: string; alert_threshold?: number }
interface FieldCatalog {
  level: IndicatorLevel
  groups: Array<{ group: string; fields: Array<{ name: string; unit: string; description: string }> }>
  functions: Array<{ name: string; signature: string; help: string }>
}
interface Validation { ok: boolean; error?: string; position?: number; pretty?: string; fields?: string[] }
interface Preview extends Validation {
  rows: Array<{ cdu_id: number | null; name: string | null; value: number | null; error: string | null; substituted: string; inputs: Record<string, number | null> }>
  note?: string
}
interface Draft {
  name: string; description: string; level: IndicatorLevel; unit: IndicatorUnit; expression: string; decimals: number
  show_on_dashboard: boolean; alert_on: boolean; alert_op: string; alert_threshold: string; alert_severity: string
}

const EMPTY: Draft = {
  name: '', description: '', level: 'cdu', unit: 'PCT', expression: '', decimals: 2, show_on_dashboard: true,
  alert_on: false, alert_op: '>', alert_threshold: '', alert_severity: 'WARN',
}
const STATUS_LABEL: Record<string, { label: string; cls: string }> = {
  ACTIVE: { label: 'работает', cls: 'badge-ok' },
  DRAFT: { label: 'черновик', cls: 'badge-neutral' },
  ARCHIVED: { label: 'в архиве', cls: 'badge-neutral' },
}
const OPERATORS = [
  { v: ' + ', label: '+' }, { v: ' - ', label: '−' }, { v: ' * ', label: '×' }, { v: ' / ', label: '÷' },
  { v: '(', label: '(' }, { v: ')', label: ')' }, { v: '; ', label: ';' },
  { v: ' > ', label: '>' }, { v: ' < ', label: '<' }, { v: ' = ', label: '=' },
]

function toDraft(i: Indicator): Draft {
  return {
    name: i.name, description: i.description ?? '', level: i.level, unit: i.unit, expression: i.expression,
    decimals: i.decimals, show_on_dashboard: i.show_on_dashboard, alert_on: !!i.alert_op,
    alert_op: i.alert_op ?? '>', alert_threshold: i.alert_threshold !== null ? String(i.alert_threshold).replace('.', ',') : '',
    alert_severity: i.alert_severity ?? 'WARN',
  }
}

function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = useState(value)
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t) }, [value, ms])
  return v
}

export default function IndicatorBuilder() {
  const qc = useQueryClient()
  const canEdit = useAuthStore((s) => s.can('formulas.edit'))
  const list = useQuery<Indicator[]>({ queryKey: ['indicators'], queryFn: async () => (await api.get('/formulas/indicators')).data })
  const templates = useQuery<Template[]>({ queryKey: ['indicator-templates'], queryFn: async () => (await api.get('/formulas/templates')).data })
  const [selected, setSelected] = useState<number | 'new' | null>(null)
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const [showArchived, setShowArchived] = useState(false)
  const current = typeof selected === 'number' ? list.data?.find((i) => i.id === selected) : undefined

  useEffect(() => {
    if (selected === null && list.data) {
      if (list.data.length) { setSelected(list.data[0].id); setDraft(toDraft(list.data[0])) } else setSelected('new')
    }
  }, [list.data, selected])

  const open = (i: Indicator) => { setSelected(i.id); setDraft(toDraft(i)) }
  const startNew = (t?: Template) => {
    setSelected('new')
    setDraft(t ? {
      ...EMPTY, name: t.name, description: t.description, level: t.level, unit: t.unit, expression: t.expression,
      alert_on: !!t.alert_op, alert_op: t.alert_op ?? '>', alert_threshold: t.alert_threshold !== undefined ? String(t.alert_threshold).replace('.', ',') : '',
    } : EMPTY)
  }

  const payload = (activate?: boolean) => ({
    name: draft.name, description: draft.description, level: draft.level, unit: draft.unit, expression: draft.expression,
    decimals: draft.decimals, show_on_dashboard: draft.show_on_dashboard,
    alert_op: draft.alert_on ? draft.alert_op : null,
    alert_threshold: draft.alert_on ? draft.alert_threshold : null,
    alert_severity: draft.alert_on ? draft.alert_severity : null,
    ...(activate !== undefined ? { activate } : {}),
  })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['indicators'] })
    qc.invalidateQueries({ queryKey: ['indicator-values'] })
  }
  const save = useMutation({
    mutationFn: async (activate: boolean | undefined) => (selected === 'new'
      ? (await api.post('/formulas/indicators', payload(activate ?? true))).data
      : (await api.put(`/formulas/indicators/${selected}`, payload(activate))).data) as Indicator,
    onSuccess: (r) => { toast.success(`Показатель «${r.name}» сохранён; версия ${r.version}.`); setSelected(r.id); setDraft(toDraft(r)); refresh() },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось сохранить пользовательский показатель')),
  })
  const setStatus = useMutation({
    mutationFn: async (status: string) => (await api.post(`/formulas/indicators/${selected}/status`, { status })).data as Indicator,
    onSuccess: (r) => { toast.success(r.status === 'ARCHIVED' ? 'Показатель перенесён в архив и скрыт из активных.' : 'Показатель восстановлен и доступен в активных.'); refresh() },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось изменить статус показателя')),
  })

  const visible = (list.data ?? []).filter((i) => showArchived || i.status !== 'ARCHIVED')
  const archivedCount = (list.data ?? []).filter((i) => i.status === 'ARCHIVED').length

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[300px_1fr]">
      <aside className="space-y-3">
        <div className="card p-2">
          {canEdit && (
            <button type="button" className="btn-primary mb-2 w-full" onClick={() => startNew()}>
              <Plus className="h-4 w-4" /> Новый показатель
            </button>
          )}
          {list.isLoading && <div className="p-3 text-sm text-slate-500">Загрузка…</div>}
          {list.data && visible.length === 0 && (
            <div className="px-3 py-4 text-center text-sm text-slate-500">Пока нет своих показателей. Начните с шаблона ниже.</div>
          )}
          {visible.map((i) => (
            <button key={i.id} type="button" onClick={() => open(i)}
              className={clsx('mb-1 block w-full rounded-xl px-3 py-2 text-left transition',
                selected === i.id ? 'bg-emerald-50 ring-1 ring-emerald-200' : 'hover:bg-slate-50')}>
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-semibold text-slate-800">{i.name}</span>
                <span className={STATUS_LABEL[i.status]?.cls}>{STATUS_LABEL[i.status]?.label}</span>
              </div>
              <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-slate-500">
                {i.level === 'cdu' ? 'по каждому ЧДУ' : 'по фонду'} · {UNIT_LABEL[i.unit]}
                {i.alert_op && <Bell className="h-3 w-3 text-amber-500" />}
                {!i.valid && <AlertTriangle className="h-3 w-3 text-red-500" />}
              </div>
            </button>
          ))}
          {archivedCount > 0 && (
            <button type="button" className="mt-1 w-full text-center text-xs text-slate-500 hover:text-slate-700" onClick={() => setShowArchived((v) => !v)}>
              {showArchived ? 'скрыть архив' : `показать архив (${archivedCount})`}
            </button>
          )}
        </div>
        {canEdit && templates.data && (
          <div className="card p-3">
            <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-slate-800"><Sparkles className="h-4 w-4 text-violet-500" /> Шаблоны</div>
            <div className="space-y-1">
              {templates.data.map((t) => (
                <button key={t.name} type="button" onClick={() => startNew(t)} title={t.description}
                  className="block w-full rounded-lg px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-violet-50 hover:text-violet-900">
                  {t.name}
                </button>
              ))}
            </div>
          </div>
        )}
      </aside>

      {selected !== null && (
        <Editor
          key={String(selected)}
          draft={draft} setDraft={setDraft} canEdit={canEdit} current={current}
          saving={save.isPending}
          onSave={(activate) => save.mutate(activate)}
          onStatus={(s) => setStatus.mutate(s)}
          onRolledBack={(r) => { setDraft(toDraft(r)); refresh() }}
        />
      )}
    </div>
  )
}

function Editor({ draft, setDraft, canEdit, current, saving, onSave, onStatus, onRolledBack }: {
  draft: Draft; setDraft: (d: Draft) => void; canEdit: boolean; current?: Indicator; saving: boolean
  onSave: (activate?: boolean) => void; onStatus: (s: string) => void; onRolledBack: (r: Indicator) => void
}) {
  const workDate = useWorkContextStore((s) => s.workDate)
  const setWorkDate = useWorkContextStore((s) => s.setWorkDate)
  const area = useRef<HTMLTextAreaElement>(null)
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft({ ...draft, [k]: v })

  const insert = (text: string, cursorBack = 0) => {
    const el = area.current
    const start = el?.selectionStart ?? draft.expression.length
    const end = el?.selectionEnd ?? draft.expression.length
    const next = draft.expression.slice(0, start) + text + draft.expression.slice(end)
    set('expression', next)
    requestAnimationFrame(() => {
      if (!el) return
      el.focus()
      const pos = start + text.length - cursorBack
      el.setSelectionRange(pos, pos)
    })
  }

  const expression = useDebounced(draft.expression)
  const preview = useQuery<Preview>({
    queryKey: ['indicator-preview', expression, draft.level, workDate],
    enabled: expression.trim().length > 0,
    placeholderData: (prev) => prev,
    queryFn: async () => (await api.post('/formulas/preview', { expression, level: draft.level, date: workDate })).data,
  })
  const p = expression.trim() ? preview.data : undefined
  const threshold = draft.alert_on && draft.alert_threshold.trim() ? Number(draft.alert_threshold.replace(/\s/g, '').replace(',', '.')) : null
  const dirty = !current || JSON.stringify(toDraft(current)) !== JSON.stringify(draft)

  return (
    <div className="space-y-4">
      <div className="card space-y-4 p-5">
        <div className="flex flex-wrap items-start gap-3">
          <label className="min-w-[240px] flex-1"><span className="field-label">Название</span>
            <input className="input" value={draft.name} disabled={!canEdit} placeholder="например: Доля ГЦБ в портфеле"
              onChange={(e) => set('name', e.target.value)} />
          </label>
          {current && (
            <div className="pt-5 text-right text-xs text-slate-500">
              <span className={STATUS_LABEL[current.status]?.cls}>{STATUS_LABEL[current.status]?.label}</span>
              <div className="mt-1">версия {current.version}{current.updated_by ? ` · ${current.updated_by}` : ''}</div>
            </div>
          )}
        </div>
        <label className="block"><span className="field-label">Пояснение (необязательно)</span>
          <input className="input-sm" value={draft.description} disabled={!canEdit} placeholder="Что показывает показатель — увидят коллеги"
            onChange={(e) => set('description', e.target.value)} />
        </label>
        <div className="flex flex-wrap gap-3">
          <label className="w-52"><span className="field-label">Считать</span>
            <select className="input-sm" value={draft.level} disabled={!canEdit} onChange={(e) => set('level', e.target.value as IndicatorLevel)}>
              <option value="cdu">по каждому ЧДУ</option>
              <option value="fund">по фонду в целом</option>
            </select>
          </label>
          <label className="w-40"><span className="field-label">Единица</span>
            <select className="input-sm" value={draft.unit} disabled={!canEdit} onChange={(e) => set('unit', e.target.value as IndicatorUnit)}>
              {Object.entries(UNIT_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="w-36"><span className="field-label">Знаков после запятой</span>
            <select className="input-sm" value={draft.decimals} disabled={!canEdit} onChange={(e) => set('decimals', Number(e.target.value))}>
              {[0, 1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>

        <FormulaInput draft={draft} canEdit={canEdit} area={area} insert={insert} onChange={(v) => set('expression', v)} validation={p} />

        <div className="grid grid-cols-1 gap-3 border-t border-slate-100 pt-4 md:grid-cols-2">
          <label className="flex items-start gap-2 text-sm text-slate-700">
            <input type="checkbox" className="mt-0.5 h-4 w-4 rounded border-slate-300 text-emerald-600" checked={draft.show_on_dashboard}
              disabled={!canEdit} onChange={(e) => set('show_on_dashboard', e.target.checked)} />
            <span>Показывать в «Сводке»<span className="block text-xs text-slate-500">{draft.level === 'cdu' ? 'плашкой в блоке каждого ЧДУ' : 'в панели «Мои показатели по фонду»'}</span></span>
          </label>
          <div className="text-sm text-slate-700">
            <label className="flex items-center gap-2">
              <input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-emerald-600" checked={draft.alert_on}
                disabled={!canEdit} onChange={(e) => set('alert_on', e.target.checked)} />
              <Bell className="h-4 w-4 text-amber-500" /> Уведомлять, если значение
            </label>
            {draft.alert_on && (
              <div className="mt-2 flex flex-wrap items-center gap-2 pl-6">
                <select className="input-sm w-32" value={draft.alert_op} disabled={!canEdit} onChange={(e) => set('alert_op', e.target.value)}>
                  {ALERT_OPS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                <input className="input-sm w-28 text-right" value={draft.alert_threshold} disabled={!canEdit} placeholder="порог"
                  onChange={(e) => set('alert_threshold', e.target.value)} />
                <select className="input-sm w-44" value={draft.alert_severity} disabled={!canEdit} onChange={(e) => set('alert_severity', e.target.value)}>
                  <option value="WARN">предупреждение</option>
                  <option value="BREACH">нарушение</option>
                  <option value="INFO">информация</option>
                </select>
                <span className="w-full text-xs text-slate-500">Уведомление появится в Центре контроля после пересчёта сводки.</span>
              </div>
            )}
          </div>
        </div>

        {canEdit && (
          <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4">
            <button type="button" className="btn-primary" disabled={saving || !draft.name.trim() || !p?.ok || (!dirty && current?.status === 'ACTIVE')}
              onClick={() => onSave(current && current.status === 'ACTIVE' ? undefined : true)}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {current ? (current.status === 'ACTIVE' ? 'Сохранить изменения' : 'Сохранить и включить') : 'Сохранить и включить'}
            </button>
            {(!current || current.status !== 'ACTIVE') && (
              <button type="button" className="btn-secondary" disabled={saving || !draft.name.trim() || !p?.ok} onClick={() => onSave(false)}>
                Сохранить черновиком
              </button>
            )}
            {current?.status === 'DRAFT' && !dirty && (
              <button type="button" className="btn-secondary" onClick={() => onStatus('ACTIVE')}><Play className="h-4 w-4" /> Включить</button>
            )}
            {current && current.status !== 'ARCHIVED' && (
              <button type="button" className="btn-ghost ml-auto" onClick={() => onStatus('ARCHIVED')}><Archive className="h-4 w-4" /> В архив</button>
            )}
          </div>
        )}
      </div>

      <PreviewPanel p={p} loading={preview.isFetching} draft={draft} threshold={threshold} workDate={workDate} setWorkDate={setWorkDate} />
      {current && <Versions id={current.id} canEdit={canEdit} onRolledBack={onRolledBack} />}
    </div>
  )
}

function FormulaInput({ draft, canEdit, area, insert, onChange, validation }: {
  draft: Draft; canEdit: boolean; area: React.RefObject<HTMLTextAreaElement>; insert: (t: string, back?: number) => void
  onChange: (v: string) => void; validation?: Validation
}) {
  const catalog = useQuery<FieldCatalog>({
    queryKey: ['indicator-fields', draft.level],
    queryFn: async () => (await api.get('/formulas/fields', { params: { level: draft.level } })).data,
  })
  const [q, setQ] = useState('')
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({ 'Стоимость по категориям': true, 'Итоги': true })
  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return (catalog.data?.groups ?? []).map((g) => ({
      ...g, fields: needle ? g.fields.filter((f) => f.name.toLowerCase().includes(needle)) : g.fields,
    })).filter((g) => g.fields.length)
  }, [catalog.data, q])

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_300px]">
      <div className="space-y-2">
        <span className="field-label">Формула</span>
        <textarea
          ref={area}
          className={clsx('input min-h-[96px] font-mono text-[14px] leading-6',
            validation && !validation.ok && 'border-red-300 focus:border-red-400 focus:ring-red-500/15')}
          value={draft.expression}
          disabled={!canEdit}
          spellCheck={false}
          placeholder="Перетащите поле справа или нажмите на него. Например: ДОЛЯ([ГЦБ]; [Итого ЧДУ])"
          onChange={(e) => onChange(e.target.value)}
        />
        {canEdit && (
          <div className="flex flex-wrap items-center gap-1">
            {OPERATORS.map((o) => (
              <button key={o.label} type="button" onClick={() => insert(o.v)}
                className="h-7 min-w-[28px] rounded-md border border-slate-200 bg-white px-1.5 font-mono text-sm text-slate-700 hover:border-emerald-300 hover:bg-emerald-50">
                {o.label}
              </button>
            ))}
            <span className="mx-1 h-5 w-px bg-slate-200" />
            {(catalog.data?.functions ?? []).map((f) => (
              <button key={f.name} type="button" title={`${f.signature}\n${f.help}`} onClick={() => insert(`${f.name}()`, 1)}
                className="h-7 rounded-md border border-violet-200 bg-violet-50 px-2 text-xs font-semibold text-violet-800 hover:bg-violet-100">
                {f.name}
              </button>
            ))}
          </div>
        )}
        {validation && (validation.ok
          ? <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 px-3 py-2 text-sm">
              <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-emerald-800"><CheckCircle2 className="h-3.5 w-3.5" /> Формула понятна системе</div>
              <PrettyFormula text={validation.pretty ?? ''} />
            </div>
          : <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              <div className="flex items-center gap-1.5 font-semibold"><XCircle className="h-4 w-4" /> {validation.error}</div>
              {validation.position !== undefined && validation.position !== null && (
                <pre className="mt-1 overflow-x-auto font-mono text-[13px] text-slate-700">{draft.expression}{'\n'}{' '.repeat(Math.max(0, validation.position))}<span className="text-red-600">▲</span></pre>
              )}
            </div>)}
        <details className="text-xs text-slate-500">
          <summary className="cursor-pointer select-none">Как писать формулы</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            <li>Поля пишутся в квадратных скобках: <code>[ГЦБ]</code>, <code>[Итого ЧДУ]</code>. Проще всего — перетащить их из списка справа.</li>
            <li>Действия: <code>+ − * /</code>, степень <code>^</code>, скобки. Дробные числа — через запятую: <code>0,5</code>.</li>
            <li>Аргументы функций разделяются точкой с запятой, как в Excel: <code>ДОЛЯ([ГЦБ]; [Итого ЧДУ])</code>.</li>
            <li>Проценты в полях уже в процентах: 12,5 означает 12,5 %. Суммы — в тенге.</li>
            <li>Если у ЧДУ нет данных для поля, результат будет пустым, а не нулём.</li>
          </ul>
        </details>
      </div>
      <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-2">
        <div className="relative mb-2">
          <Search className="pointer-events-none absolute left-2 top-2 h-4 w-4 text-slate-400" />
          <input className="input-sm pl-7" placeholder="Найти поле" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="max-h-[360px] space-y-1 overflow-y-auto pr-1">
          {groups.map((g) => {
            const isOpen = !!q || openGroups[g.group]
            return (
              <div key={g.group}>
                <button type="button" onClick={() => setOpenGroups((s) => ({ ...s, [g.group]: !s[g.group] }))}
                  className="flex w-full items-center gap-1 py-1 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500 hover:text-slate-700">
                  {isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />} {g.group}
                  <span className="font-normal text-slate-400">{g.fields.length}</span>
                </button>
                {isOpen && (
                  <div className="flex flex-wrap gap-1 pb-1 pl-1">
                    {g.fields.map((f) => (
                      <FieldChip key={f.name} name={f.name} small draggable={canEdit} title={f.description}
                        onClick={canEdit ? () => insert(`[${f.name}]`) : undefined} />
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function PreviewPanel({ p, loading, draft, threshold, workDate, setWorkDate }: {
  p?: Preview; loading: boolean; draft: Draft; threshold: number | null; workDate: string; setWorkDate: (d: string) => void
}) {
  const [open, setOpen] = useState<string | null>(null)
  return (
    <div className="card p-5">
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div className="mr-auto">
          <div className="flex items-center gap-2 text-base font-semibold text-slate-900">
            Проверка на данных {loading && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
          </div>
          <div className="text-xs text-slate-500">Значения по рассчитанной сводке на дату. Нажмите на строку, чтобы увидеть подстановку.</div>
        </div>
        <label className="w-40"><span className="field-label">Дата</span>
          <input type="date" className="input-sm" value={workDate} onChange={(e) => setWorkDate(e.target.value)} />
        </label>
      </div>
      {!draft.expression.trim() && <div className="rounded-xl bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">Введите формулу — результат появится здесь</div>}
      {p && !p.ok && <div className="text-sm text-slate-500">Исправьте формулу, чтобы увидеть результат.</div>}
      {p?.ok && p.note && <div className="rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800">{p.note}</div>}
      {p?.ok && p.rows.length > 0 && (
        <table className="detail-table w-full">
          <thead><tr><th>{draft.level === 'cdu' ? 'ЧДУ' : ''}</th><th className="num">Значение</th><th>Как получилось</th></tr></thead>
          <tbody>
            {p.rows.map((r) => {
              const key = String(r.cdu_id ?? 'fund')
              const alarm = breached(draft.alert_on ? draft.alert_op : null, threshold, r.value)
              return (
                <tr key={key} className={clsx('cursor-pointer align-top', alarm && 'bg-red-50/60')} onClick={() => setOpen(open === key ? null : key)}>
                  <td className="font-medium">{r.name}</td>
                  <td className={clsx('num font-semibold', alarm && 'text-red-700')}>
                    {alarm && <Bell className="mr-1 inline h-3.5 w-3.5" />}
                    {r.error ? <span className="font-normal text-slate-400">{r.error}</span> : formatIndicator(r.value, draft.unit, draft.decimals)}
                  </td>
                  <td className="text-xs text-slate-600">
                    <span className="font-mono">= {r.substituted}</span>
                    {open === key && (
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
                        {Object.entries(r.inputs).map(([k, v]) => (
                          <span key={k}><FieldChip name={k} small /> = {v === null ? 'пусто' : v.toLocaleString('ru-RU', { maximumFractionDigits: 4 })}</span>
                        ))}
                      </div>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}

function Versions({ id, canEdit, onRolledBack }: { id: number; canEdit: boolean; onRolledBack: (r: Indicator) => void }) {
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()
  const versions = useQuery<Array<{ version: number; snapshot: Record<string, unknown>; comment: string | null; created_by: string | null; created_at: string | null }>>({
    queryKey: ['indicator-versions', id],
    enabled: open,
    queryFn: async () => (await api.get(`/formulas/indicators/${id}/versions`)).data,
  })
  const rollback = useMutation({
    mutationFn: async (v: number) => (await api.post(`/formulas/indicators/${id}/rollback/${v}`)).data as Indicator,
    onSuccess: (r) => { toast.success(`Прежняя версия восстановлена; создана текущая версия ${r.version}.`); onRolledBack(r); qc.invalidateQueries({ queryKey: ['indicator-versions', id] }) },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось восстановить версию показателя')),
  })
  return (
    <div className="card p-4">
      <button type="button" className="flex items-center gap-2 text-sm font-semibold text-slate-800" onClick={() => setOpen((v) => !v)}>
        <History className="h-4 w-4 text-slate-500" /> История версий {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </button>
      {open && (
        <div className="mt-3 space-y-2">
          {versions.data?.map((v, i) => (
            <div key={`${v.version}-${i}`} className="flex flex-wrap items-start gap-3 rounded-xl border border-slate-200 px-3 py-2 text-sm">
              <span className="badge-neutral">v{v.version}</span>
              <div className="min-w-0 flex-1">
                <div className="font-medium text-slate-800">{String(v.snapshot.name)}</div>
                <PrettyFormula text={String(v.snapshot.expression)} className="text-xs" />
                <div className="text-[11px] text-slate-500">
                  {v.created_at ? formatDate(v.created_at) : ''} · {v.created_by ?? '—'}{v.comment ? ` · ${v.comment}` : ''}
                </div>
              </div>
              {canEdit && i > 0 && (
                <button type="button" className="btn-ghost h-8 px-2 text-xs" disabled={rollback.isPending} onClick={() => rollback.mutate(v.version)}>
                  <RotateCcw className="h-3.5 w-3.5" /> Вернуть
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
