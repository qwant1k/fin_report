import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertOctagon, Archive, BellRing, CheckCircle2, CircleDot, Search, UserRoundCheck } from 'lucide-react'
import toast from 'react-hot-toast'

import AlertControlCard from '@/components/AlertControlCard'
import { api } from '@/lib/api'
import { useConfirm } from '@/lib/confirm'
import { apiErrorMessage } from '@/lib/notifications'
import type { AlertItem, CDU } from '@/lib/types'
import { cn } from '@/lib/cn'

type StatusFilter = 'ACTIVE' | 'NEW' | 'IN_PROGRESS' | 'RESOLVED'

const statusOptions: Array<{ value: StatusFilter; label: string; icon: typeof BellRing }> = [
  { value: 'ACTIVE', label: 'Все активные', icon: BellRing },
  { value: 'NEW', label: 'Новые', icon: CircleDot },
  { value: 'IN_PROGRESS', label: 'В работе', icon: UserRoundCheck },
  { value: 'RESOLVED', label: 'Решённые', icon: CheckCircle2 },
]

export default function AlertsPage() {
  const [status, setStatus] = useState<StatusFilter>('ACTIVE')
  const [severity, setSeverity] = useState('')
  const [cduId, setCduId] = useState('')
  const [query, setQuery] = useState('')
  const confirm = useConfirm()
  const qc = useQueryClient()

  const alerts = useQuery<AlertItem[]>({
    queryKey: ['alerts', 'journal', status, severity, cduId],
    queryFn: async () => {
      const params: Record<string, string | boolean | number> = { since_days: 3650 }
      if (status === 'ACTIVE') params.only_unresolved = true
      else params.status = status
      if (severity) params.severity = severity
      if (cduId) params.cdu_id = cduId
      return (await api.get('/dashboard/alerts', { params })).data
    },
  })

  const cdus = useQuery<CDU[]>({
    queryKey: ['cdus'],
    queryFn: async () => (await api.get('/settings/cdus')).data,
  })

  const take = useMutation({
    mutationFn: async (item: AlertItem) => (await api.put(`/dashboard/alerts/${item.id}/take-in-work`)).data,
    onSuccess: () => {
      toast.success('Уведомление взято в работу.')
      for (const key of ['alerts', 'workday']) void qc.invalidateQueries({ queryKey: [key] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось взять уведомление в работу')),
  })

  const resolve = useMutation({
    mutationFn: async ({ item, comment }: { item: AlertItem; comment?: string }) =>
      (await api.put(`/dashboard/alerts/${item.id}/resolve`, { comment })).data,
    onSuccess: () => {
      toast.success('Проблема отмечена как решённая и сохранена в журнале.')
      for (const key of ['alerts', 'dashboard', 'workday']) void qc.invalidateQueries({ queryKey: [key] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось закрыть уведомление')),
  })

  const closeAlert = async (item: AlertItem) => {
    const { confirmed, comment } = await confirm({
      title: item.severity === 'CRITICAL' ? 'Закрыть критическое нарушение?' : 'Отметить проблему решённой?',
      description: 'Решение, автор и время останутся в журнале контроля.',
      confirmLabel: 'Отметить решённой',
      requireComment: item.severity === 'CRITICAL' ? 'Что сделано для устранения нарушения' : undefined,
    })
    if (confirmed) resolve.mutate({ item, comment })
  }

  const rows = alerts.data ?? []
  const visible = useMemo(() => {
    const text = query.trim().toLocaleLowerCase('ru')
    if (!text) return rows
    return rows.filter((item) => [item.message, item.cdu_name, item.cdu_short_name, item.alert_type]
      .some((value) => String(value ?? '').toLocaleLowerCase('ru').includes(text)))
  }, [query, rows])

  const counters = {
    critical: rows.filter((item) => item.severity === 'CRITICAL' && !item.is_resolved).length,
    warning: rows.filter((item) => item.severity === 'WARN' && !item.is_resolved).length,
    inProgress: rows.filter((item) => item.status === 'IN_PROGRESS').length,
    resolved: rows.filter((item) => item.status === 'RESOLVED').length,
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900"><Archive className="h-6 w-6 text-emerald-600" /> Журнал контроля</h1>
          <p className="mt-1 text-sm text-slate-500">Нарушения, ответственные и история решений по всем проверкам системы</p>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Counter label="Критические" value={counters.critical} tone="rose" icon={AlertOctagon} />
          <Counter label="Предупреждения" value={counters.warning} tone="amber" icon={BellRing} />
          <Counter label="В работе" value={counters.inProgress} tone="indigo" icon={UserRoundCheck} />
          <Counter label="Решённые" value={counters.resolved} tone="emerald" icon={CheckCircle2} />
        </div>
      </header>

      <section className="card p-4">
        <div className="flex flex-wrap gap-2 border-b border-slate-100 pb-4">
          {statusOptions.map(({ value, label, icon: Icon }) => (
            <button key={value} type="button" onClick={() => setStatus(value)} className={cn('control-chip h-9 px-3 text-xs', status === value && 'border-slate-800 bg-slate-800 text-white')}>
              <Icon className="h-3.5 w-3.5" /> {label}
            </button>
          ))}
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-[minmax(260px,1fr)_220px_260px]">
          <label className="relative">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} className="input h-9 w-full pl-9 text-sm" placeholder="Поиск по тексту или ЧДУ" />
          </label>
          <select value={severity} onChange={(event) => setSeverity(event.target.value)} className="input h-9 text-sm">
            <option value="">Любая важность</option>
            <option value="CRITICAL">Критические</option>
            <option value="WARN">Предупреждения</option>
            <option value="INFO">Информационные</option>
          </select>
          <select value={cduId} onChange={(event) => setCduId(event.target.value)} className="input h-9 text-sm">
            <option value="">Все ЧДУ и портфели</option>
            {(cdus.data ?? []).map((cdu) => <option key={cdu.id} value={cdu.id}>{cdu.short_name} — {cdu.name}</option>)}
          </select>
        </div>
      </section>

      <section className="space-y-3">
        {alerts.isLoading && <div className="card p-10 text-center text-sm text-slate-500">Загружаем журнал контроля…</div>}
        {alerts.isError && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">Не удалось загрузить журнал контроля.</div>}
        {visible.map((item) => (
          <AlertControlCard
            key={item.id}
            alert={item}
            busy={take.isPending || resolve.isPending}
            onTake={(row) => take.mutate(row)}
            onResolve={(row) => void closeAlert(row)}
          />
        ))}
        {!alerts.isLoading && !alerts.isError && visible.length === 0 && (
          <div className="card p-10 text-center">
            <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-500" />
            <div className="mt-2 font-semibold text-slate-800">Записей по выбранным условиям нет</div>
            <div className="mt-1 text-sm text-slate-500">Измените фильтры или выберите другой статус.</div>
          </div>
        )}
      </section>
    </div>
  )
}

function Counter({ label, value, tone, icon: Icon }: { label: string; value: number; tone: 'rose' | 'amber' | 'indigo' | 'emerald'; icon: typeof BellRing }) {
  const styles = {
    rose: 'border-rose-200 bg-rose-50 text-rose-700',
    amber: 'border-amber-200 bg-amber-50 text-amber-700',
    indigo: 'border-indigo-200 bg-indigo-50 text-indigo-700',
    emerald: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  }
  return (
    <div className={cn('min-w-28 rounded-xl border px-3 py-2', styles[tone])}>
      <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide"><Icon className="h-3.5 w-3.5" /> {label}</div>
      <div className="mt-0.5 text-xl font-bold">{value}</div>
    </div>
  )
}
