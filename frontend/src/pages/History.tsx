import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, Calendar } from 'lucide-react'

import { api } from '@/lib/api'
import { formatDate, formatNumber, formatPct } from '@/lib/format'

interface Row {
  date: string
  cdu_short: string
  total_mv: number
  ytm: number
  duration: number
  benchmark_duration: number | null
}

export default function HistoryPage() {
  const [days, setDays] = useState(90)
  const { data, refetch } = useQuery<Row[]>({
    queryKey: ['history', days],
    queryFn: async () => (await api.get('/dashboard/history', { params: { days } })).data,
  })

  const reports = useQuery<any[]>({
    queryKey: ['reports'],
    queryFn: async () => (await api.get('/reports/')).data,
  })

  return (
    <div className="space-y-6">
      <header className="flex justify-between items-center flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-bold">История</h1>
          <p className="text-sm text-slate-500">Сводка расчётов и сгенерированных отчётов</p>
        </div>
        <div className="flex gap-2 items-center">
          <Calendar className="w-4 h-4 text-slate-400" />
          <select className="input w-32" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={30}>30 дней</option>
            <option value={90}>90 дней</option>
            <option value={180}>180 дней</option>
            <option value={365}>1 год</option>
          </select>
          <button onClick={() => refetch()} className="btn-secondary">Обновить</button>
        </div>
      </header>

      <div className="card overflow-hidden">
        <div className="p-4 border-b font-semibold">Дневные итоги по ЧДУ</div>
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>Дата</th>
                <th>ЧДУ</th>
                <th>Total MV</th>
                <th>YTM</th>
                <th>Duration</th>
                <th>Benchmark Dur</th>
              </tr>
            </thead>
            <tbody>
              {(data ?? []).slice().reverse().map((r, i) => (
                <tr key={i}>
                  <td>{formatDate(r.date)}</td>
                  <td>{r.cdu_short}</td>
                  <td className="text-right">{formatNumber(r.total_mv, 0)}</td>
                  <td className="text-right">{formatPct(r.ytm)}</td>
                  <td className="text-right">{formatNumber(r.duration, 2)}</td>
                  <td className="text-right">{r.benchmark_duration != null ? formatNumber(r.benchmark_duration, 2) : '—'}</td>
                </tr>
              ))}
              {!data?.length && <tr><td colSpan={6} className="text-center text-slate-400 py-6">Нет данных</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card overflow-hidden">
        <div className="p-4 border-b font-semibold">Сгенерированные отчёты</div>
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Дата отчёта</th>
                <th>Тип</th>
                <th>Создан</th>
                <th>Файл</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(reports.data ?? []).map((r) => (
                <tr key={r.id}>
                  <td>{r.id}</td>
                  <td>{formatDate(r.report_date)}</td>
                  <td>{r.report_type}</td>
                  <td>{formatDate(r.generated_at)}</td>
                  <td className="text-xs text-slate-500">{r.file_path}</td>
                  <td>
                    <a href={`/api/reports/${r.id}/download`} className="btn-secondary px-2 py-1">
                      <Download className="w-4 h-4" />
                    </a>
                  </td>
                </tr>
              ))}
              {!reports.data?.length && <tr><td colSpan={6} className="text-center text-slate-400 py-6">Отчёты ещё не создавались</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
