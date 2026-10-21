import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { Check, ChevronRight, ClipboardCheck, ShieldBan, X } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { useConfirm } from '@/lib/confirm'
import { apiErrorMessage } from '@/lib/notifications'
import { formatDate } from '@/lib/format'

interface ApprovalTask {
  key: string
  kind: 'operation' | 'report'
  entity: string
  entity_id: number
  type_label: string
  title: string
  subtitle: string
  status: string
  requested_by: string | null
  requested_at: string | null
  own_operation: boolean
  can_approve: boolean
  can_reject: boolean
  before: Record<string, string>
  after: Record<string, string>
}

interface ApprovalQueue {
  count: number
  items: ApprovalTask[]
}

function DiffColumn({ title, values, tone }: { title: string; values: Record<string, string>; tone: 'before' | 'after' }) {
  return (
    <div className={`min-w-0 rounded-lg border p-2.5 ${tone === 'after' ? 'border-emerald-200 bg-emerald-50/70' : 'border-slate-200 bg-slate-50'}`}>
      <div className={`mb-1.5 text-[11px] font-bold uppercase tracking-wide ${tone === 'after' ? 'text-emerald-700' : 'text-slate-500'}`}>{title}</div>
      <dl className="space-y-1 text-xs">
        {Object.entries(values).map(([label, value]) => (
          <div key={label} className="flex justify-between gap-2">
            <dt className="truncate text-slate-500">{label}</dt>
            <dd className="max-w-[60%] truncate text-right font-mono font-medium text-slate-800" title={value}>{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

export default function QuickApprovalDrawer() {
  const [open, setOpen] = useState(false)
  const can = useAuthStore((state) => state.can)
  const allowed = can('manual.operations.approve') || can('reports.approve') || can('reports.reject')
  const confirm = useConfirm()
  const qc = useQueryClient()
  const queue = useQuery<ApprovalQueue>({
    queryKey: ['approvals'],
    queryFn: async () => (await api.get('/approvals')).data,
    enabled: allowed,
    refetchInterval: 30_000,
  })

  const decision = useMutation({
    mutationFn: async ({ task, action, comment }: { task: ApprovalTask; action: 'approve' | 'reject'; comment?: string }) => {
      const url = task.kind === 'report'
        ? `/reports/${task.entity_id}/${action}`
        : `/accounting/${task.entity}/${task.entity_id}/${action}`
      return (await api.post(url, { comment })).data
    },
    onSuccess: (_data, variables) => {
      toast.success(variables.action === 'approve' ? 'Задача согласована.' : 'Задача отклонена с комментарием.')
      for (const key of ['approvals', 'accounting', 'reports', 'dashboard', 'workday', 'category-breakdown']) {
        qc.invalidateQueries({ queryKey: [key] })
      }
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось сохранить решение')),
  })

  if (!allowed) return null

  const decide = async (task: ApprovalTask, action: 'approve' | 'reject') => {
    const { confirmed, comment } = await confirm({
      title: action === 'approve' ? 'Согласовать задачу?' : 'Отклонить задачу?',
      description: action === 'approve'
        ? 'Изменение вступит в силу и попадёт в расчёты.'
        : 'Инициатор увидит причину и сможет исправить данные.',
      confirmLabel: action === 'approve' ? 'Согласовать' : 'Отклонить',
      tone: action === 'approve' ? 'default' : 'danger',
      requireComment: action === 'reject' ? 'Причина отклонения' : undefined,
    })
    if (confirmed && (action === 'approve' || comment)) decision.mutate({ task, action, comment })
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="control-chip relative h-8 gap-1.5 px-2.5 text-xs"
        aria-label="Открыть очередь согласования"
      >
        <ClipboardCheck className="h-4 w-4" />
        <span className="hidden sm:inline">4-Eyes</span>
        {(queue.data?.count ?? 0) > 0 && (
          <span className="flex min-w-5 items-center justify-center rounded-full bg-amber-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
            {queue.data?.count}
          </span>
        )}
      </button>

      <AnimatePresence>
        {open && (
          <div className="fixed inset-0 z-[90]">
            <motion.div className="absolute inset-0 bg-slate-950/30 backdrop-blur-[2px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(false)} />
            <motion.aside
              role="dialog"
              aria-modal="true"
              aria-label="Очередь согласования"
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', stiffness: 320, damping: 34 }}
              className="absolute right-0 top-0 flex h-full w-full max-w-xl flex-col bg-white shadow-2xl"
            >
              <div className="flex items-start justify-between border-b border-slate-200 px-5 py-4">
                <div>
                  <h2 className="flex items-center gap-2 text-lg font-bold text-slate-900"><ClipboardCheck className="h-5 w-5 text-indigo-600" /> Быстрое согласование</h2>
                  <p className="mt-0.5 text-sm text-slate-500">Изменения, ожидающие вторую пару глаз</p>
                </div>
                <button type="button" onClick={() => setOpen(false)} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100" aria-label="Закрыть"><X className="h-5 w-5" /></button>
              </div>

              <div className="min-h-0 flex-1 space-y-3 overflow-y-auto bg-slate-50/70 p-4">
                {queue.isLoading && <div className="p-8 text-center text-sm text-slate-500">Загрузка очереди…</div>}
                {queue.isError && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">Не удалось загрузить очередь согласования.</div>}
                {queue.data?.items.map((task) => (
                  <article key={task.key} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-xs font-semibold uppercase tracking-wide text-indigo-600">{task.type_label}</div>
                        <h3 className="truncate font-semibold text-slate-900" title={task.title}>{task.title}</h3>
                        <div className="text-xs text-slate-500">{task.subtitle} · {task.requested_by || 'система'} · {formatDate(task.requested_at)}</div>
                      </div>
                      <ChevronRight className="h-4 w-4 shrink-0 text-slate-300" />
                    </div>
                    <div className="mt-3 grid grid-cols-[1fr_auto_1fr] items-center gap-2">
                      <DiffColumn title="Было" values={task.before} tone="before" />
                      <ChevronRight className="h-4 w-4 text-slate-400" />
                      <DiffColumn title="Стало" values={task.after} tone="after" />
                    </div>
                    {task.own_operation ? (
                      <div className="mt-3 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800">
                        <ShieldBan className="h-4 w-4 shrink-0" /> Нельзя согласовать собственную операцию.
                      </div>
                    ) : (
                      <div className="mt-3 flex justify-end gap-2">
                        {task.can_reject && <button type="button" disabled={decision.isPending} onClick={() => void decide(task, 'reject')} className="btn-secondary h-8 px-3 text-xs text-rose-700"><X className="h-3.5 w-3.5" /> Отклонить</button>}
                        {task.can_approve && <button type="button" disabled={decision.isPending} onClick={() => void decide(task, 'approve')} className="btn-primary h-8 px-3 text-xs"><Check className="h-3.5 w-3.5" /> Согласовать</button>}
                      </div>
                    )}
                  </article>
                ))}
                {queue.data && queue.data.items.length === 0 && (
                  <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center">
                    <Check className="mx-auto h-8 w-8 text-emerald-500" />
                    <div className="mt-2 font-semibold text-slate-800">Очередь пуста</div>
                    <div className="text-sm text-slate-500">Все задачи рассмотрены.</div>
                  </div>
                )}
              </div>
            </motion.aside>
          </div>
        )}
      </AnimatePresence>
    </>
  )
}
