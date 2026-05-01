import { useState } from 'react'
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
  const isAdmin = useAuthStore((s) => s.isAdmin())
  const [tab, setTab] = useState<'cdus' | 'limits'>('cdus')

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
                  <CduRow key={c.id} cdu={c} canEdit={isAdmin} onSave={(u) => saveCdu.mutate(u)} onDelete={() => delCdu.mutate(c.id)} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
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
                  <LimitRow key={l.id} limit={l} cdus={cdus.data ?? []} canEdit={isAdmin} onSave={(u) => saveLimit.mutate(u)} />
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
