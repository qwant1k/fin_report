import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, CheckCircle2, Plus } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { KasePrice } from '@/lib/types'
import { formatDate, formatNumber, formatPct } from '@/lib/format'

export default function KasePage() {
  const today = new Date().toISOString().slice(0, 10)
  const [reportDate, setReportDate] = useState(today)
  const qc = useQueryClient()

  const { data } = useQuery<KasePrice[]>({
    queryKey: ['kase-prices', reportDate],
    queryFn: async () => (await api.get('/kase/prices', { params: { report_date: reportDate } })).data,
  })

  const refresh = useMutation({
    mutationFn: async () => (await api.post('/kase/refresh', null, { params: { report_date: reportDate } })).data,
    onSuccess: (r) => {
      toast.success(`Получено: ${r.fetched}, новых записей: ${r.new_rows}`)
      qc.invalidateQueries({ queryKey: ['kase-prices'] })
    },
  })

  const reconcile = useMutation({
    mutationFn: async () => (await api.post('/kase/reconcile', null, { params: { report_date: reportDate } })).data,
    onSuccess: (r) => toast.success(`Сверено цен: ${r.checked}`),
  })

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-bold">KASE котировки</h1>
          <p className="text-sm text-slate-500">Цены закрытия, YTM, дюрация для сверки портфельных оценок</p>
        </div>
        <div className="flex items-center gap-2">
          <input type="date" className="input w-44" value={reportDate} onChange={(e) => setReportDate(e.target.value)} />
          <button onClick={() => refresh.mutate()} disabled={refresh.isPending} className="btn-primary">
            <RefreshCw className={`w-4 h-4 ${refresh.isPending ? 'animate-spin' : ''}`} /> Обновить с KASE
          </button>
          <button onClick={() => reconcile.mutate()} className="btn-secondary">
            <CheckCircle2 className="w-4 h-4" /> Сверить с портфелем
          </button>
        </div>
      </header>

      <div className="card overflow-hidden">
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>Код</th>
                <th>ISIN</th>
                <th>Наименование</th>
                <th>Close</th>
                <th>YTM</th>
                <th>НКД</th>
                <th>Duration</th>
                <th>Источник</th>
                <th>Получено</th>
              </tr>
            </thead>
            <tbody>
              {(data ?? []).map((r) => (
                <tr key={r.id}>
                  <td className="font-medium">{r.instrument_code}</td>
                  <td>{r.isin ?? '—'}</td>
                  <td>{r.instrument_name ?? '—'}</td>
                  <td className="text-right">{r.close_price != null ? formatNumber(r.close_price, 4) : '—'}</td>
                  <td className="text-right">{r.ytm != null ? formatPct(r.ytm) : '—'}</td>
                  <td className="text-right">{(r as any).accrued_interest != null ? formatNumber((r as any).accrued_interest, 2) : '—'}</td>
                  <td className="text-right">{r.duration != null ? formatNumber(r.duration, 2) : '—'}</td>
                  <td>{r.source}</td>
                  <td>{formatDate(r.fetched_at)}</td>
                </tr>
              ))}
              {!data?.length && <tr><td colSpan={9} className="text-center text-slate-400 py-6">Котировок нет — обновите с KASE</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
