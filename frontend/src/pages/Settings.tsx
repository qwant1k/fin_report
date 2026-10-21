import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Save, X } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { categoryLabel } from '@/lib/displayLabels'
import { CDU, CDULimit } from '@/lib/types'
import { formatPct } from '@/lib/format'
import { useAuthStore } from '@/lib/auth'
import { useConfirm } from '@/lib/confirm'
import { apiErrorMessage } from '@/lib/notifications'

const CATS = ['CASH', 'GOV_BONDS', 'REVERSE_REPO', 'MFO_BONDS', 'AGENCY_BONDS', 'RECEIVABLES', 'OTHER']
type NewCduPayload = Omit<CDU, 'id'>

const EMPTY_CDU: NewCduPayload = {
  name: '',
  short_name: '',
  participant_code: '',
  participant_code_prefix: '',
  portfolio_type: 'PRIVATE_CDU',
  portfolio_code: null,
  share_target_pct: 0,
  contact_email: null,
  contact_manager: null,
  is_active: true,
}

export default function SettingsPage() {
  const qc = useQueryClient()
  const can = useAuthStore((s) => s.can)
  const confirm = useConfirm()
  const canEdit = can('settings.edit')
  const canEditFormats = can('cdu_formats.edit')
  const [tab, setTab] = useState<'cdus' | 'limits' | 'formats'>('cdus')
  const [showNewCdu, setShowNewCdu] = useState(false)

  const cdus = useQuery<CDU[]>({
    queryKey: ['cdus'],
    queryFn: async () => (await api.get('/settings/cdus')).data,
  })
  const limits = useQuery<CDULimit[]>({
    queryKey: ['limits'],
    queryFn: async () => (await api.get('/settings/limits')).data,
  })

  const saveCdu = useMutation({
    mutationFn: async (c: CDU) => (await api.put(`/settings/cdus/${c.id}`, c)).data,
    onSuccess: (_result, c) => {
      toast.success(`ЧДУ «${c.short_name || c.name}» сохранён в справочнике.`)
      qc.invalidateQueries({ queryKey: ['cdus'] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось сохранить ЧДУ')),
  })

  const createCdu = useMutation({
    mutationFn: async (payload: NewCduPayload) => (await api.post('/settings/cdus', payload)).data as CDU,
    onSuccess: (created) => {
      toast.success(`ЧДУ «${created.short_name}» добавлен и доступен для загрузок, операций и отчётов.`)
      setShowNewCdu(false)
      qc.invalidateQueries({ queryKey: ['cdus'] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось добавить ЧДУ')),
  })

  const delCdu = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/settings/cdus/${id}`)).data,
    onSuccess: () => {
      toast.success('ЧДУ удалён из справочника.')
      qc.invalidateQueries({ queryKey: ['cdus'] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось удалить ЧДУ')),
  })

  const handleDeleteCdu = async (c: CDU) => {
    const { confirmed } = await confirm({
      title: 'Удалить ЧДУ?',
      description: `«${c.name}» (${c.short_name}) будет удалён из справочника. Это затронет фильтры и отчёты, ссылающиеся на этот ЧДУ.`,
      tone: 'danger',
      confirmLabel: 'Удалить',
    })
    if (confirmed) delCdu.mutate(c.id)
  }

  const saveLimit = useMutation({
    mutationFn: async (l: CDULimit) =>
      (l.id
        ? api.put(`/settings/limits/${l.id}`, l)
        : api.post('/settings/limits', l)
      ).then((r) => r.data),
    onSuccess: (_result, limit) => {
      toast.success(`Лимит для категории «${categoryLabel(limit.instrument_category)}» сохранён.`)
      qc.invalidateQueries({ queryKey: ['limits'] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось сохранить лимит ЧДУ')),
  })

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Настройки</h1>
        <p className="text-sm text-slate-500">Справочники ЧДУ, лимиты и инструменты</p>
      </header>

      <div className="flex gap-2 border-b border-slate-200">
        <button onClick={() => setTab('cdus')} className={`px-4 py-2 ${tab === 'cdus' ? 'border-b-2 border-kdif-green text-kdif-green font-semibold' : 'text-slate-500'}`}>ЧДУ</button>
        <button onClick={() => setTab('limits')} className={`px-4 py-2 ${tab === 'limits' ? 'border-b-2 border-kdif-green text-kdif-green font-semibold' : 'text-slate-500'}`}>Лимиты</button>
        <button onClick={() => setTab('formats')} className={`px-4 py-2 ${tab === 'formats' ? 'border-b-2 border-kdif-green text-kdif-green font-semibold' : 'text-slate-500'}`}>Форматы файлов</button>
      </div>

      {tab === 'cdus' && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold text-slate-800">Справочник ЧДУ</h2>
              <p className="text-sm text-slate-500">Добавляйте управляющих вручную и настраивайте их распознавание в загружаемых файлах.</p>
            </div>
            {canEdit && !showNewCdu && (
              <button type="button" className="btn-primary" onClick={() => setShowNewCdu(true)}>
                <Plus className="mr-1 h-4 w-4" /> Добавить ЧДУ
              </button>
            )}
          </div>

          {showNewCdu && (
            <NewCduForm
              pending={createCdu.isPending}
              onCancel={() => setShowNewCdu(false)}
              onCreate={(payload) => createCdu.mutate(payload)}
            />
          )}

          <div className="card overflow-hidden">
            <div className="table-wrap">
              <table className="kdif-table">
                <thead>
                  <tr>
                    <th>Имя</th>
                    <th>Краткое</th>
                    <th>Код участника</th>
                    <th>Префикс</th>
                    <th>Тип</th>
                    <th>Целевая доля</th>
                    <th>Email</th>
                    <th>Активен</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {(cdus.data ?? []).map((c) => (
                    <CduRow key={c.id} cdu={c} canEdit={canEdit} onSave={(u) => saveCdu.mutate(u)} onDelete={() => handleDeleteCdu(c)} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {tab === 'formats' && (
        <CDUFormatsPanel cdus={cdus.data ?? []} canEdit={canEditFormats} />
      )}

      {tab === 'limits' && (
        <div className="card overflow-hidden">
          <div className="table-wrap">
            <table className="kdif-table">
              <thead>
                <tr>
                  <th>ЧДУ</th>
                  <th>Категория</th>
                  <th>Min</th>
                  <th>Max</th>
                  <th>Hard</th>
                  <th>Soft</th>
                  <th>Действует с</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {(limits.data ?? []).map((l) => (
                  <LimitRow key={l.id} limit={l} cdus={cdus.data ?? []} canEdit={canEdit} onSave={(u) => saveLimit.mutate(u)} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function NewCduForm({ pending, onCreate, onCancel }: {
  pending: boolean
  onCreate: (payload: NewCduPayload) => void
  onCancel: () => void
}) {
  const [value, setValue] = useState<NewCduPayload>({ ...EMPTY_CDU })

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    const required = [value.name, value.short_name, value.participant_code, value.participant_code_prefix]
    if (required.some((item) => !item.trim())) {
      toast.error('Заполните полное и краткое наименование, код участника и префикс распознавания.')
      return
    }
    if (value.portfolio_type !== 'PRIVATE_CDU' && !value.portfolio_code?.trim()) {
      toast.error('Для портфеля НБ РК укажите код портфеля.')
      return
    }
    if (value.share_target_pct < 0 || value.share_target_pct > 100) {
      toast.error('Целевая доля должна быть от 0 до 100%.')
      return
    }
    onCreate({
      ...value,
      name: value.name.trim(),
      short_name: value.short_name.trim(),
      participant_code: value.participant_code.trim(),
      participant_code_prefix: value.participant_code_prefix.trim(),
      portfolio_code: value.portfolio_code?.trim() || null,
      contact_email: value.contact_email?.trim() || null,
      contact_manager: value.contact_manager?.trim() || null,
    })
  }

  return (
    <form onSubmit={submit} className="card space-y-4 border border-emerald-200 bg-emerald-50/40 p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-slate-900">Новый ЧДУ</h3>
          <p className="text-sm text-slate-500">Поля со звёздочкой обязательны. Код и префикс используются для автоматического распознавания файлов.</p>
        </div>
        <button type="button" onClick={onCancel} className="rounded p-1 text-slate-500 hover:bg-white hover:text-slate-800" title="Закрыть форму">
          <X className="h-5 w-5" />
        </button>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Field label="Полное наименование *">
          <input className="input" value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} placeholder="АО «Название компании»" autoFocus />
        </Field>
        <Field label="Краткое наименование *">
          <input className="input" value={value.short_name} onChange={(e) => setValue({ ...value, short_name: e.target.value })} placeholder="Название" />
        </Field>
        <Field label="Код участника *">
          <input className="input font-mono" value={value.participant_code} onChange={(e) => setValue({ ...value, participant_code: e.target.value })} placeholder="Код из Trade Report" />
        </Field>
        <Field label="Префикс распознавания *">
          <input className="input font-mono" value={value.participant_code_prefix} onChange={(e) => setValue({ ...value, participant_code_prefix: e.target.value })} placeholder="Первые символы кода" />
        </Field>
        <Field label="Тип портфеля">
          <select className="input" value={value.portfolio_type} onChange={(e) => setValue({ ...value, portfolio_type: e.target.value as CDU['portfolio_type'], portfolio_code: e.target.value === 'PRIVATE_CDU' ? null : value.portfolio_code })}>
            <option value="PRIVATE_CDU">Частный ЧДУ</option>
            <option value="NBRK_OWN">НБ РК — собственный портфель</option>
            <option value="NBRK_RESERVE">НБ РК — специальный резерв</option>
          </select>
        </Field>
        {value.portfolio_type !== 'PRIVATE_CDU' && (
          <Field label="Код портфеля НБ РК *">
            <input className="input font-mono" value={value.portfolio_code ?? ''} onChange={(e) => setValue({ ...value, portfolio_code: e.target.value })} placeholder="Например, 310138-1" />
          </Field>
        )}
        <Field label="Целевая доля, %">
          <input type="number" min="0" max="100" step="0.01" className="input" value={value.share_target_pct} onChange={(e) => setValue({ ...value, share_target_pct: Number(e.target.value) })} />
        </Field>
        <Field label="Email">
          <input type="email" className="input" value={value.contact_email ?? ''} onChange={(e) => setValue({ ...value, contact_email: e.target.value })} placeholder="reports@example.kz" />
        </Field>
        <Field label="Ответственный менеджер">
          <input className="input" value={value.contact_manager ?? ''} onChange={(e) => setValue({ ...value, contact_manager: e.target.value })} placeholder="Ф.И.О." />
        </Field>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-emerald-200 pt-4">
        <label className="inline-flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={value.is_active} onChange={(e) => setValue({ ...value, is_active: e.target.checked })} />
          Сразу включить ЧДУ в загрузки и отчёты
        </label>
        <div className="flex gap-2">
          <button type="button" className="btn-secondary" onClick={onCancel} disabled={pending}>Отмена</button>
          <button type="submit" className="btn-primary" disabled={pending}>
            <Save className="mr-1 h-4 w-4" /> {pending ? 'Добавление…' : 'Добавить ЧДУ'}
          </button>
        </div>
      </div>
    </form>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="space-y-1 text-sm font-medium text-slate-700">
      <span>{label}</span>
      {children}
    </label>
  )
}

function CduRow({ cdu, canEdit, onSave, onDelete }: {
  cdu: CDU; canEdit: boolean; onSave: (c: CDU) => void; onDelete: () => void
}) {
  const [v, setV] = useState(cdu)
  return (
    <tr>
      <td><input className="input py-1" value={v.name} disabled={!canEdit} onChange={(e) => setV({ ...v, name: e.target.value })} /></td>
      <td><input className="input py-1" value={v.short_name} disabled={!canEdit} onChange={(e) => setV({ ...v, short_name: e.target.value })} /></td>
      <td><input className="input py-1 font-mono" value={v.participant_code} disabled={!canEdit} onChange={(e) => setV({ ...v, participant_code: e.target.value })} /></td>
      <td><input className="input py-1" value={v.participant_code_prefix} disabled={!canEdit} onChange={(e) => setV({ ...v, participant_code_prefix: e.target.value })} /></td>
      <td>
        <select className="input min-w-40 py-1" value={v.portfolio_type} disabled={!canEdit} onChange={(e) => setV({ ...v, portfolio_type: e.target.value as CDU['portfolio_type'] })}>
          <option value="PRIVATE_CDU">Частный ЧДУ</option>
          <option value="NBRK_OWN">НБ РК — собственный</option>
          <option value="NBRK_RESERVE">НБ РК — спецрезерв</option>
        </select>
      </td>
      <td><input className="input py-1 text-right" value={v.share_target_pct} disabled={!canEdit} onChange={(e) => setV({ ...v, share_target_pct: Number(e.target.value) })} /></td>
      <td><input className="input py-1" value={v.contact_email ?? ''} disabled={!canEdit} onChange={(e) => setV({ ...v, contact_email: e.target.value })} /></td>
      <td>
        <input type="checkbox" checked={v.is_active} disabled={!canEdit} onChange={(e) => setV({ ...v, is_active: e.target.checked })} />
      </td>
      <td className="flex gap-1">
        {canEdit && <button onClick={() => onSave(v)} className="btn-secondary px-2 py-1"><Save className="w-4 h-4" /></button>}
        {canEdit && <button onClick={onDelete} className="btn-secondary text-red-600 px-2 py-1"><Trash2 className="w-4 h-4" /></button>}
      </td>
    </tr>
  )
}

function LimitRow({ limit, cdus, canEdit, onSave }: {
  limit: CDULimit; cdus: CDU[]; canEdit: boolean; onSave: (l: CDULimit) => void
}) {
  const [v, setV] = useState(limit)
  const cduName = cdus.find((c) => c.id === v.cdu_id)?.short_name ?? '?'
  return (
    <tr>
      <td>{cduName}</td>
      <td>
        <select className="input py-1" value={v.instrument_category} disabled={!canEdit} onChange={(e) => setV({ ...v, instrument_category: e.target.value })}>
          {CATS.map((c) => <option key={c} value={c}>{categoryLabel(c)}</option>)}
        </select>
      </td>
      <td><input className="input py-1 text-right w-24" value={v.min_limit_pct} disabled={!canEdit} onChange={(e) => setV({ ...v, min_limit_pct: Number(e.target.value) })} /></td>
      <td><input className="input py-1 text-right w-24" value={v.max_limit_pct} disabled={!canEdit} onChange={(e) => setV({ ...v, max_limit_pct: Number(e.target.value) })} /></td>
      <td><input className="input py-1 text-right w-24" value={v.hard_limit_pct} disabled={!canEdit} onChange={(e) => setV({ ...v, hard_limit_pct: Number(e.target.value) })} /></td>
      <td><input className="input py-1 text-right w-24" value={v.soft_limit_pct} disabled={!canEdit} onChange={(e) => setV({ ...v, soft_limit_pct: Number(e.target.value) })} /></td>
      <td><input type="date" className="input py-1" value={v.valid_from} disabled={!canEdit} onChange={(e) => setV({ ...v, valid_from: e.target.value })} /></td>
      <td>{canEdit && <button onClick={() => onSave(v)} className="btn-secondary px-2 py-1"><Save className="w-4 h-4" /></button>}</td>
    </tr>
  )
}

// ─────────────── CDU file format overrides ───────────────

const FORMAT_FIELDS: Array<{ key: string; label: string }> = [
  { key: 'deal_number', label: 'Сделка №' },
  { key: 'order_number', label: 'Заявка №' },
  { key: 'trade_time', label: 'Время сделки' },
  { key: 'kp', label: 'Код участника (КП)' },
  { key: 'regime_code', label: 'Режим торгов' },
  { key: 'instrument_code', label: 'Код инструмента' },
  { key: 'status', label: 'Статус сделки' },
  { key: 'participant_code', label: 'Код участника' },
  { key: 'trade_account', label: 'Счёт' },
  { key: 'volume', label: 'Объём' },
  { key: 'price', label: 'Цена' },
  { key: 'amount', label: 'Сумма' },
  { key: 'nkd', label: 'НКД' },
  { key: 'currency', label: 'Валюта' },
]

interface CDUFormat {
  id?: number
  cdu_id: number
  cdu_name?: string | null
  field_aliases: Record<string, string[]>
  header_row_index: number
  is_active: boolean
  updated_by?: string | null
  updated_at?: string | null
}

function CDUFormatsPanel({ cdus, canEdit }: { cdus: CDU[]; canEdit: boolean }) {
  const qc = useQueryClient()
  const [selectedCduId, setSelectedCduId] = useState<number | null>(
    cdus[0]?.id ?? null,
  )

  const fmt = useQuery<CDUFormat>({
    queryKey: ['cdu-format', selectedCduId],
    queryFn: async () =>
      (await api.get(`/cdu-formats/${selectedCduId}`)).data,
    enabled: selectedCduId != null,
  })

  const save = useMutation({
    mutationFn: async (payload: CDUFormat) =>
      (await api.post(`/cdu-formats/${payload.cdu_id}`, payload)).data,
    onSuccess: () => {
      toast.success('Правила распознавания файла ЧДУ сохранены.')
      qc.invalidateQueries({ queryKey: ['cdu-format', selectedCduId] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось сохранить правила распознавания файла')),
  })

  const remove = useMutation({
    mutationFn: async () => (await api.delete(`/cdu-formats/${selectedCduId}`)).data,
    onSuccess: () => {
      toast.success('Индивидуальные правила удалены; применяется формат по умолчанию.')
      qc.invalidateQueries({ queryKey: ['cdu-format', selectedCduId] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось восстановить формат по умолчанию')),
  })

  const [draft, setDraft] = useState<Record<string, string>>({})

  // Reload draft when the selected CDU or its server-side aliases change.
  useEffect(() => {
    if (!fmt.data || selectedCduId == null) return
    const aliases = fmt.data.field_aliases ?? {}
    const next: Record<string, string> = {}
    for (const f of FORMAT_FIELDS) {
      next[f.key] = (aliases[f.key] ?? []).join(', ')
    }
    setDraft(next)
  }, [selectedCduId, fmt.data])

  const handleSave = () => {
    if (selectedCduId == null) return
    const built: Record<string, string[]> = {}
    for (const f of FORMAT_FIELDS) {
      const raw = (draft[f.key] ?? '').trim()
      if (!raw) continue
      const list = raw.split(',').map((s) => s.trim()).filter(Boolean)
      if (list.length) built[f.key] = list
    }
    save.mutate({
      cdu_id: selectedCduId,
      field_aliases: built,
      header_row_index: fmt.data?.header_row_index ?? 0,
      is_active: fmt.data?.is_active ?? true,
    })
  }

  return (
    <div className="space-y-4">
      <div className="card p-4">
        <p className="text-sm text-slate-600">
          Перекрытия имён колонок XLSX-файла для конкретного ЧДУ. Если CDU присылает
          колонку с нестандартным заголовком (например, <em>«Номер сделки»</em> вместо
          <em> «Сделка №»</em>), укажите альтернативные названия через запятую. При парсинге
          этот список проверяется первым; если совпадений нет — используется встроенный словарь.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm font-medium text-slate-700">ЧДУ:</label>
        <select
          className="input py-1 max-w-md"
          value={selectedCduId ?? ''}
          onChange={(e) => setSelectedCduId(Number(e.target.value) || null)}
        >
          {cdus.map((c) => (
            <option key={c.id} value={c.id}>
              {c.short_name} — {c.name}
            </option>
          ))}
        </select>
        {fmt.data?.updated_at && (
          <span className="text-xs text-slate-500">
            обновлено: {fmt.data.updated_by ?? '—'}, {new Date(fmt.data.updated_at).toLocaleString()}
          </span>
        )}
      </div>

      {selectedCduId != null && (
        <div className="card overflow-hidden">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>Поле</th>
                <th>Канонический ключ</th>
                <th>Альтернативные заголовки (через запятую)</th>
              </tr>
            </thead>
            <tbody>
              {FORMAT_FIELDS.map((f) => (
                <tr key={f.key}>
                  <td className="whitespace-nowrap font-medium">{f.label}</td>
                  <td className="font-mono text-xs text-slate-500">{f.key}</td>
                  <td>
                    <input
                      className="input py-1 w-full"
                      placeholder="напр.: номер сделки, deal id"
                      value={draft[f.key] ?? ''}
                      disabled={!canEdit}
                      onChange={(e) =>
                        setDraft((d) => ({ ...d, [f.key]: e.target.value }))
                      }
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {canEdit && (
            <div className="flex items-center justify-end gap-2 border-t border-slate-200 p-3">
              <button
                onClick={() => remove.mutate()}
                className="btn-secondary text-red-600"
                disabled={!fmt.data?.id}
              >
                <Trash2 className="w-4 h-4 mr-1" /> Сбросить
              </button>
              <button
                onClick={handleSave}
                className="btn-primary"
                disabled={save.isPending}
              >
                <Save className="w-4 h-4 mr-1" /> Сохранить
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
