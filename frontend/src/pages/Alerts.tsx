import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, AlertOctagon, Info, CheckCircle2 } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { AlertItem } from '@/lib/types'
import { formatDate } from '@/lib/format'

const sevIcon = {
  INFO: <Info className="w-4 h-4 text-blue-500" />,
  WARN: <AlertTriangle className="w-4 h-4 text-amber-500" />,
  CRITICAL: <AlertOctagon className="w-4 h-4 text-red-500" />,
}

const sevClass = {
  INFO: 'bg-blue-50 border-blue-200',
  WARN: 'bg-amber-50 border-amber-200',
  CRITICAL: 'bg-red-50 border-red-200',
}

export default function AlertsPage() {
  const qc = useQueryClient()
  const { data } = useQuery<AlertItem[]>({
    queryKey: ['alerts'],
    queryFn: async () => (await api.get('/dashboard/alerts', { params: { since_days: 60 } })).data,
  })

  const resolve = useMutation({
    mutationFn: async (id: number) => (await api.put(`/dashboard/alerts/${id}/resolve`)).data,
    onSuccess: () => {
      toast.success('Алерт отмечен как решённый')
      qc.invalidateQueries({ queryKey: ['alerts'] })
    },
  })

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Алерты</h1>
        <p className="text-sm text-slate-500">Нарушения лимитов и предупреждения системы</p>
      </header>

      <div className="space-y-3">
        {(data ?? []).map((a) => (
          <div key={a.id} className={`card p-4 border-l-4 ${sevClass[a.severity]}`}>
            <div className="flex items-start justify-between">
              <div className="flex items-start gap-3">
                {sevIcon[a.severity]}
                <div>
                  <div className="font-medium">{a.message}</div>
                  <div className="text-xs text-slate-500 mt-1">
                    {formatDate(a.alert_date)} · тип: {a.alert_type} · severity: {a.severity}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {a.is_resolved && <span className="badge-ok"><CheckCircle2 className="w-3 h-3 inline mr-1" />Решено</span>}
                {!a.is_resolved && (
                  <button onClick={() => resolve.mutate(a.id)} className="btn-secondary text-xs">
                    Закрыть
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
        {!data?.length && (
          <div className="card p-8 text-center text-slate-400">Нарушений не зарегистрировано 🎉</div>
        )}
      </div>
    </div>
  )
}
