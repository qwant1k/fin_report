import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Save } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { CDU, CDULimit } from '@/lib/types'
import { formatPct } from '@/lib/format'
import { useAuthStore } from '@/lib/auth'

const CATS = ['CASH', 'GOV_BONDS', 'REVERSE_REPO', 'MFO_BONDS', 'AGENCY_BONDS', 'RECEIVABLES', 'OTHER']

export default function SettingsPage() {
  const qc = useQueryClient()
  const can = useAuthStore((s) => s.can)
  const canEdit = can('settings.edit')
  const canEditFormats = can('cdu_formats.edit')
  const [tab, setTab] = useState<'cdus' | 'limits' | 'formats'>('cdus')

  const cdus = useQuery<CDU[]>({
    queryKey: ['cdus'],
    queryFn: async () => (await api.get('/settings/cdus')).data,
  })
  const limits = useQuery<CDULimit[]>({
    queryKey: ['limits'],
    queryFn: async () => (await api.get('/settings/limits')).data,
  })

  const saveCdu = useMutation({
    mutationFn: async (c: CDU) =>
      (c.id
        ? api.put(`/settings/cdus/${c.id}`, c)
        : api.post('/settings/cdus', c)
      ).then((r) => r.data),
    onSuccess: () => {
      toast.success('Сохранено')
      qc.invalidateQueries({ queryKey: ['cdus'] })
    },
  })

  const delCdu = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/settings/cdus/${id}`)).data,
    onSuccess: () => {
      toast.success('Удалено')
      qc.invalidateQueries({ queryKey: ['cdus'] })
    },
  })

  const saveLimit = useMutation({
    mutationFn: async (l: CDULimit) =>
      (l.id
        ? api.put(`/settings/limits/${l.id}`, l)
        : api.post('/settings/limits', l)
      ).then((r) => r.data),
    onSuccess: () => {
      toast.success('Лимит сохранён')
      qc.invalidateQueries({ queryKey: ['limits'] })
    },
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
        <div className="card overflow-hidden">
          <div className="table-wrap">
            <table className="kdif-table">
              <thead>
                <tr>
                  <th>Имя</th>
                  <th>Краткое</th>
                  <th>Префикс</th>
                  <th>Целевая доля</th>
                  <th>Email</th>
                  <th>Активен</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {(cdus.data ?? []).map((c) => (
                  <CduRow key={c.id} cdu={c} canEdit={canEdit} onSave={(u) => saveCdu.mutate(u)} onDelete={() => delCdu.mutate(c.id)} />
                ))}
              </tbody>
            </table>
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

function CduRow({ cdu, canEdit, onSave, onDelete }: {
  cdu: CDU; canEdit: boolean; onSave: (c: CDU) => void; onDelete: () => void
}) {
  const [v, setV] = useState(cdu)
  return (
    <tr>
      <td><input className="input py-1" value={v.name} disabled={!canEdit} onChange={(e) => setV({ ...v, name: e.target.value })} /></td>
      <td><input className="input py-1" value={v.short_name} disabled={!canEdit} onChange={(e) => setV({ ...v, short_name: e.target.value })} /></td>
      <td><input className="input py-1" value={v.participant_code_prefix} disabled={!canEdit} onChange={(e) => setV({ ...v, participant_code_prefix: e.target.value })} /></td>
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
          {CATS.map((c) => <option key={c}>{c}</option>)}
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
      toast.success('Формат сохранён')
      qc.invalidateQueries({ queryKey: ['cdu-format', selectedCduId] })
    },
    onError: () => toast.error('Не удалось сохранить'),
  })

  const remove = useMutation({
    mutationFn: async () => (await api.delete(`/cdu-formats/${selectedCduId}`)).data,
    onSuccess: () => {
      toast.success('Сброшено к умолчанию')
      qc.invalidateQueries({ queryKey: ['cdu-format', selectedCduId] })
    },
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
