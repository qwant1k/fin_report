import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Plus } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { MBM } from '@/lib/types'
import { formatDate, formatNumber, formatPct } from '@/lib/format'

export default function MbmPage() {
  const qc = useQueryClient()
  const { data } = useQuery<MBM[]>({
    queryKey: ['mbm'],
    queryFn: async () => (await api.get('/mbm/', { params: { days: 180 } })).data,
  })
  const [manualDate, setManualDate] = useState(new Date().toISOString().slice(0, 10))
  const [manualYtm, setManualYtm] = useState('')
  const [manualDur, setManualDur] = useState('')

  const refresh = useMutation({
    mutationFn: async () => (await api.post('/mbm/refresh')).data,
    onSuccess: () => {
      toast.success('MBM обновлён')
      qc.invalidateQueries({ queryKey: ['mbm'] })
    },
  })

  const manual = useMutation({
    mutationFn: async () =>
      (await api.post('/mbm/manual', {
        index_date: manualDate,
        ytm_value: manualYtm ? Number(manualYtm) : null,
        duration: manualDur ? Number(manualDur) : null,
      })).data,
    onSuccess: () => {
      toast.success('MBM сохранён')
      qc.invalidateQueries({ queryKey: ['mbm'] })
    },
  })

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-bold">MBM index</h1>
          <p className="text-sm text-slate-500">Бенчмарк-доходность и дюрация (НБ РК / KASE)</p>
        </div>
        <button onClick={() => refresh.mutate()} disabled={refresh.isPending} className="btn-primary">
          <RefreshCw className={`w-4 h-4 ${refresh.isPending ? 'animate-spin' : ''}`} /> Обновить
        </button>
      </header>

      <div className="card p-4 space-y-3">
        <h2 className="font-semibold">Ввод вручную</h2>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <input type="date" className="input" value={manualDate} onChange={(e) => setManualDate(e.target.value)} />
          <input className="input" placeholder="YTM (доля, напр. 0.155)" value={manualYtm} onChange={(e) => setManualYtm(e.target.value)} />
          <input className="input" placeholder="Duration (лет)" value={manualDur} onChange={(e) => setManualDur(e.target.value)} />
          <button onClick={() => manual.mutate()} className="btn-primary">
            <Plus className="w-4 h-4" /> Сохранить
          </button>
        </div>
      </div>

      <div className="card overflow-hidden">
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr><th>Дата</th><th>YTM</th><th>Duration</th><th>Источник</th><th>Получено</th></tr>
            </thead>
            <tbody>
              {(data ?? []).map((r) => (
                <tr key={r.id}>
                  <td>{formatDate(r.index_date)}</td>
                  <td className="text-right">{r.ytm_value != null ? formatPct(r.ytm_value) : '—'}</td>
                  <td className="text-right">{r.duration != null ? formatNumber(r.duration, 2) : '—'}</td>
                  <td>{r.source}</td>
                  <td>{formatDate(r.fetched_at)}</td>
                </tr>
              ))}
              {!data?.length && <tr><td colSpan={5} className="text-center text-slate-400 py-6">Нет данных</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
