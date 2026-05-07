import { useQuery } from '@tanstack/react-query'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { api } from '@/lib/api'

interface HistoryRow {
  date: string
  cdu_id: number
  cdu_short: string
  total_mv: number
  ytm: number
  duration: number
}

interface Props {
  from?: string
  to?: string
}

const colors = ['#1F6B38', '#70AD47', '#FFA000', '#1565C0', '#7E57C2']

export default function HistoryChart({ from, to }: Props = {}) {
  const { data } = useQuery<HistoryRow[]>({
    queryKey: ['history-chart', from, to],
    queryFn: async () => {
      const params: Record<string, string | number> = {}
      if (from) params.from = from
      if (to) params.to = to
      if (!from) params.days = 90
      return (await api.get('/dashboard/history', { params })).data
    },
  })

  // pivot to date → cdu → mv
  const pivoted = (() => {
    const map = new Map<string, Record<string, number | string>>()
    const cdus = new Set<string>()
    for (const r of data ?? []) {
      cdus.add(r.cdu_short)
      const cur = map.get(r.date) ?? { date: r.date }
      cur[r.cdu_short] = r.total_mv
      map.set(r.date, cur)
    }
    return { rows: Array.from(map.values()).sort((a, b) => String(a.date).localeCompare(String(b.date))), cdus: Array.from(cdus) }
  })()

  if (!pivoted.rows.length) {
    return <div className="h-72 flex items-center justify-center text-slate-400 text-sm">Нет истории расчётов</div>
  }

  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={pivoted.rows}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => (v / 1e9).toFixed(1) + ' млрд'} />
          <Tooltip formatter={(v: number) => v.toLocaleString('ru-RU')} />
          <Legend />
          {pivoted.cdus.map((cdu, i) => (
            <Line
              key={cdu}
              type="monotone"
              dataKey={cdu}
              stroke={colors[i % colors.length]}
              strokeWidth={2}
              dot={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
