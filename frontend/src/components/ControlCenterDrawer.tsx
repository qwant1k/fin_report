import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertOctagon, Bell, CheckCircle2, ListChecks, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'

import AlertControlCard from '@/components/AlertControlCard'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { useConfirm } from '@/lib/confirm'
import { apiErrorMessage } from '@/lib/notifications'
import type { AlertItem } from '@/lib/types'
import { cn } from '@/lib/cn'

type Filter = 'ALL' | 'CRITICAL' | 'IN_PROGRESS'

export default function ControlCenterDrawer() {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState<Filter>('ALL')
  const can = useAuthStore((state) => state.can)
  const allowed = can('page.alerts')
  const confirm = useConfirm()
  const qc = useQueryClient()

  const alerts = useQuery<AlertItem[]>({
    queryKey: ['alerts', 'active'],
    queryFn: async () => (await api.get('/dashboard/alerts', { params: { only_unresolved: true, since_days: 365 } })).data,
    enabled: allowed,
    refetchInterval: 30_000,
  })

  const take = useMutation({
    mutationFn: async (item: AlertItem) => (await api.put(`/dashboard/alerts/${item.id}/take-in-work`)).data,
    onSuccess: () => {
      toast.success('Уведомление взято в работу.')
      void qc.invalidateQueries({ queryKey: ['alerts'] })
      void qc.invalidateQueries({ queryKey: ['workday'] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось взять уведомление в работу')),
  })

  const resolve = useMutation({
    mutationFn: async ({ item, comment }: { item: AlertItem; comment?: string }) =>
      (await api.put(`/dashboard/alerts/${item.id}/resolve`, { comment })).data,
    onSuccess: () => {
      toast.success('Проблема отмечена как решённая.')
      for (const key of ['alerts', 'dashboard', 'workday']) void qc.invalidateQueries({ queryKey: [key] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось закрыть уведомление')),
  })

  const closeAlert = async (item: AlertItem) => {
    const { confirmed, comment } = await confirm({
      title: item.severity === 'CRITICAL' ? 'Закрыть критическое нарушение?' : 'Отметить проблему решённой?',
      description: 'Запись останется в журнале контроля вместе с автором и временем решения.',
      confirmLabel: 'Отметить решённой',
      requireComment: item.severity === 'CRITICAL' ? 'Что сделано для устранения нарушения' : undefined,
    })
    if (confirmed) resolve.mutate({ item, comment })
  }

  const rows = alerts.data ?? []
  const critical = rows.filter((item) => item.severity === 'CRITICAL').length
  const inProgress = rows.filter((item) => item.status === 'IN_PROGRESS').length
  const visible = useMemo(() => rows.filter((item) => {
    if (filter === 'CRITICAL') return item.severity === 'CRITICAL'
    if (filter === 'IN_PROGRESS') return item.status === 'IN_PROGRESS'
    return true
  }), [filter, rows])

  if (!allowed) return null

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn('control-chip relative h-8 gap-1.5 px-2.5 text-xs', critical > 0 && 'border-rose-200 bg-rose-50 text-rose-700')}
        aria-label="Открыть центр контроля"
      >
        <Bell className="h-4 w-4" />
        <span className="hidden sm:inline">Контроль</span>
        {rows.length > 0 && (
          <span className={cn('flex min-w-5 items-center justify-center rounded-full px-1.5 py-0.5 text-[10px] font-bold text-white', critical > 0 ? 'bg-rose-600' : 'bg-amber-500')}>
            {rows.length > 99 ? '99+' : rows.length}
          </span>
        )}
      </button>

      <AnimatePresence>
        {open && (
          <div className="fixed inset-0 z-[95]">
            <motion.div className="absolute inset-0 bg-slate-950/30 backdrop-blur-[2px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(false)} />
            <motion.aside
              role="dialog"
              aria-modal="true"
              aria-label="Центр контроля"
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', stiffness: 320, damping: 34 }}
              className="absolute right-0 top-0 flex h-full w-full max-w-2xl flex-col bg-white shadow-2xl"
            >
              <div className="border-b border-slate-200 px-5 py-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h2 className="flex items-center gap-2 text-lg font-bold text-slate-900"><Bell className="h-5 w-5 text-amber-600" /> Центр контроля</h2>
                    <p className="mt-0.5 text-sm text-slate-500">Текущие нарушения, предупреждения и ответственные</p>
                  </div>
                  <button type="button" onClick={() => setOpen(false)} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100" aria-label="Закрыть"><X className="h-5 w-5" /></button>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {([
                    ['ALL', `Все активные · ${rows.length}`, ListChecks],
                    ['CRITICAL', `Критические · ${critical}`, AlertOctagon],
                    ['IN_PROGRESS', `В работе · ${inProgress}`, CheckCircle2],
                  ] as const).map(([value, label, Icon]) => (
                    <button key={value} type="button" onClick={() => setFilter(value)} className={cn('control-chip h-8 px-3 text-xs', filter === value && 'border-slate-800 bg-slate-800 text-white')}>
                      <Icon className="h-3.5 w-3.5" /> {label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="min-h-0 flex-1 space-y-3 overflow-y-auto bg-slate-50/70 p-4">
                {alerts.isLoading && <div className="p-10 text-center text-sm text-slate-500">Загружаем текущие уведомления…</div>}
                {alerts.isError && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">Не удалось загрузить центр контроля.</div>}
                {visible.map((item) => (
                  <AlertControlCard
                    key={item.id}
                    alert={item}
                    compact
                    busy={take.isPending || resolve.isPending}
                    onTake={(row) => take.mutate(row)}
                    onResolve={(row) => void closeAlert(row)}
                    onNavigate={() => setOpen(false)}
                  />
                ))}
                {!alerts.isLoading && !alerts.isError && visible.length === 0 && (
                  <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center">
                    <CheckCircle2 className="mx-auto h-9 w-9 text-emerald-500" />
                    <div className="mt-2 font-semibold text-slate-800">Активных проблем нет</div>
                    <div className="mt-1 text-sm text-slate-500">Все проверки пройдены или замечания уже решены.</div>
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between border-t border-slate-200 bg-white px-5 py-3">
                <span className="text-xs text-slate-500">История решений сохраняется для аудита</span>
                <Link to="/alerts" onClick={() => setOpen(false)} className="btn-secondary h-8 px-3 text-xs">
                  Открыть журнал контроля
                </Link>
              </div>
            </motion.aside>
          </div>
        )}
      </AnimatePresence>
    </>
  )
}
