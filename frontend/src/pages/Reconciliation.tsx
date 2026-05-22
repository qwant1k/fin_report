import { useState, useEffect } from 'react'
import { CheckCircle, AlertTriangle, XCircle, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

interface ReconItem {
  id: number
  cdu_id: number | null
  recon_date: string
  recon_type: string
  status: string
  expected_value: number | null
  actual_value: number | null
  deviation: number | null
  tolerance: number | null
  details_json: string | null
  created_at: string
}

export default function ReconciliationPage() {
  const [items, setItems] = useState<ReconItem[]>([])
  const [loading, setLoading] = useState(false)
  const [runDate, setRunDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [runLoading, setRunLoading] = useState(false)
  const canRun = useAuthStore((s) => s.can('reconciliation.run'))

  const fetchList = async () => {
    setLoading(true)
    try {
      const res = await api.get('/reconciliation/list')
      setItems(res.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchList()
  }, [])

  const handleRunAll = async () => {
    setRunLoading(true)
    try {
      await api.post('/reconciliation/run-all', null, { params: { recon_date: runDate } })
      await fetchList()
    } finally {
      setRunLoading(false)
    }
  }

  const statusIcon = (s: string) => {
    if (s === 'MATCHED') return <CheckCircle className="w-4 h-4 text-emerald-600" />
    if (s === 'MISMATCH') return <XCircle className="w-4 h-4 text-amber-600" />
    if (s === 'PENDING') return <Loader2 className="w-4 h-4 text-slate-400 animate-spin" />
    return <AlertTriangle className="w-4 h-4 text-red-600" />
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-800">Сверка первички</h1>
        {canRun && (
        <div className="flex items-center gap-2">
          <input
            type="date"
            value={runDate}
            onChange={(e) => setRunDate(e.target.value)}
            className="input text-sm"
          />
          <button onClick={handleRunAll} disabled={runLoading} className="btn btn-primary">
            {runLoading ? 'Выполняется…' : 'Запустить сверку'}
          </button>
        </div>
        )}
      </div>

      {loading && <div className="text-sm text-slate-500">Загрузка…</div>}

      <div className="bg-white rounded-lg border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-600">
            <tr>
              <th className="px-4 py-2 text-left">Дата</th>
              <th className="px-4 py-2 text-left">Тип</th>
              <th className="px-4 py-2 text-left">Статус</th>
              <th className="px-4 py-2 text-right">Ожидалось</th>
              <th className="px-4 py-2 text-right">Факт</th>
              <th className="px-4 py-2 text-right">Разница</th>
              <th className="px-4 py-2 text-left">Детали</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.id} className="border-t hover:bg-slate-50">
                <td className="px-4 py-2">{r.recon_date}</td>
                <td className="px-4 py-2">{r.recon_type}</td>
                <td className="px-4 py-2 flex items-center gap-1">
                  {statusIcon(r.status)} {r.status}
                </td>
                <td className="px-4 py-2 text-right">{r.expected_value?.toLocaleString('ru-KZ') ?? '-'}</td>
                <td className="px-4 py-2 text-right">{r.actual_value?.toLocaleString('ru-KZ') ?? '-'}</td>
                <td className="px-4 py-2 text-right">{r.deviation?.toLocaleString('ru-KZ') ?? '-'}</td>
                <td className="px-4 py-2 max-w-xs truncate" title={r.details_json ?? ''}>
                  {r.details_json ? JSON.parse(r.details_json).note || r.details_json.slice(0, 60) : '-'}
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-slate-400">
                  Нет данных — запустите сверку
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
