import { useMemo, useState, type ReactNode } from 'react'
import {
  type LucideIcon,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  Loader2,
  Lock,
  AlertTriangle,
  XCircle,
} from 'lucide-react'

import { cn } from '@/lib/cn'

/**
 * Единая модель статуса шага дня.
 * done        — шаг завершён без замечаний
 * in_progress — выполняется (расчёт, парсинг и т.п.)
 * warning     — завершён, но есть замечания, не блокирует движение дальше
 * error       — есть проблема, требующая решения; блокирует последующие шаги
 * blocked     — недоступен, пока не закрыты предыдущие шаги
 * pending     — ещё не начат
 */
export type StepStatus = 'done' | 'in_progress' | 'warning' | 'error' | 'blocked' | 'pending'

export interface DayProcessStep {
  id: string
  title: string
  icon: LucideIcon
  status: StepStatus
  /** короткая подпись под заголовком, напр. "12 файлов · обновлено в 09:14" */
  meta?: string
  /** количество замечаний/нарушений, отображается бейджем */
  issuesCount?: number
  /** главное действие шага — кандидат на "Next Best Action" */
  action?: { label: string; onClick: () => void }
  /** причина блокировки, если status === 'blocked' */
  blockedReason?: string
  /** содержимое разворачиваемой детали (остаёмся на том же экране) */
  detail?: ReactNode
  /** шаг частично выполнен, но не мешает идти дальше (напр. загружены не все ЧДУ) */
  nonBlocking?: boolean
  /** реально идёт фоновая работа (крутится индикатор) */
  busy?: boolean
}

const STATUS_LABEL: Record<StepStatus, string> = {
  done: 'Готово',
  in_progress: 'Выполняется',
  warning: 'Есть замечания',
  error: 'Требует внимания',
  blocked: 'Недоступно',
  pending: 'Не начато',
}

const STATUS_TEXT: Record<StepStatus, string> = {
  done: 'text-emerald-700',
  in_progress: 'text-sky-700',
  warning: 'text-amber-700',
  error: 'text-red-700',
  blocked: 'text-slate-400',
  pending: 'text-slate-500',
}

function StatusBadge({ step }: { step: DayProcessStep }) {
  const cls =
    step.status === 'done'
      ? 'badge-ok'
      : step.status === 'warning'
        ? 'badge-warn'
        : step.status === 'error'
          ? 'badge-breach'
          : step.status === 'in_progress'
            ? 'badge-info'
            : 'badge-neutral'
  return (
    <span className={cls}>
      {STATUS_LABEL[step.status]}
      {!!step.issuesCount && step.issuesCount > 0 ? ` · ${step.issuesCount}` : ''}
    </span>
  )
}

function StepIcon({ step }: { step: DayProcessStep }) {
  const Icon = step.icon

  if (step.status === 'done') {
    return (
      <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-emerald-500 text-white shadow-soft">
        <CheckCircle2 className="h-5 w-5" />
      </div>
    )
  }
  if (step.status === 'error') {
    return (
      <div className="relative flex h-11 w-11 items-center justify-center rounded-2xl bg-red-500 text-white shadow-soft">
        <XCircle className="h-5 w-5" />
        <span className="absolute -inset-0.5 rounded-2xl ring-4 ring-red-500/25 motion-safe:animate-pulse motion-reduce:animate-none" />
      </div>
    )
  }
  if (step.status === 'warning') {
    return (
      <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-amber-500 text-white shadow-soft">
        <AlertTriangle className="h-5 w-5" />
      </div>
    )
  }
  if (step.status === 'in_progress') {
    return (
      <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-sky-500 text-white shadow-soft">
        {step.busy || !step.nonBlocking
          ? <Loader2 className="h-5 w-5 motion-safe:animate-spin" />
          : <Icon className="h-5 w-5" />}
      </div>
    )
  }
  if (step.status === 'blocked') {
    return (
      <div className="flex h-11 w-11 items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50 text-slate-400">
        <Lock className="h-4 w-4" />
      </div>
    )
  }
  return (
    <div className="flex h-11 w-11 items-center justify-center rounded-2xl border-2 border-slate-200 bg-white text-slate-400">
      <Icon className="h-5 w-5" />
    </div>
  )
}

interface Props {
  steps: DayProcessStep[]
  /** переход на полноценный экран шага (сохраняет глубокие сценарии для опытных пользователей) */
  onOpenFullScreen?: (stepId: string) => void
  className?: string
}

/**
 * Единый операционный центр рабочего дня: горизонтальный таймлайн шагов
 * (Загрузка -> Парсинг -> Сверка -> Алерты -> Отчёт), с раскрытием деталей
 * на этом же экране и одной главной кнопкой "следующее действие".
 */
export default function DayProcessTimeline({ steps, onOpenFullScreen, className }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(
    () => steps.find((s) => s.status === 'error' || s.status === 'warning' || s.status === 'in_progress')?.id ?? null,
  )

  const doneCount = steps.filter((s) => s.status === 'done').length
  const progressPct = steps.length ? Math.round((doneCount / steps.length) * 100) : 0
  const allDone = steps.length > 0 && doneCount === steps.length

  // Правило приоритета: ошибка > предупреждение > выполняется > не начато.
  // Частично выполненный шаг (nonBlocking) не держит процесс: следующий шаг уже доступен.
  const nextAction = useMemo(() => {
    const blocking = steps.filter((s) => !s.nonBlocking)
    return (
      steps.find((s) => s.status === 'error') ??
      blocking.find((s) => s.status === 'warning') ??
      blocking.find((s) => s.status === 'in_progress') ??
      blocking.find((s) => s.status === 'pending') ??
      steps.find((s) => s.status === 'warning' || s.status === 'in_progress' || s.status === 'pending')
    )
  }, [steps])

  const expandedStep = steps.find((s) => s.id === expandedId) ?? null

  return (
    <div className={cn('card overflow-hidden', className)}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div>
          <h2 className="section-title">Ход рабочего дня</h2>
          <p className="mt-0.5 text-sm text-slate-500">
            Выполнено {doneCount} из {steps.length} шагов
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="h-2 w-40 overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-brand-gradient transition-[width] duration-500 ease-out"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <span className="text-sm font-semibold tabular-nums text-slate-700">{progressPct}%</span>
        </div>
      </div>

      {/* Горизонтальный таймлайн — desktop */}
      <div className="hidden items-start gap-0 overflow-x-auto px-5 pt-5 lg:flex">
        {steps.map((step, i) => (
          <div key={step.id} className="flex flex-1 items-center last:flex-none">
            <button
              type="button"
              onClick={() => setExpandedId((v) => (v === step.id ? null : step.id))}
              aria-expanded={expandedId === step.id}
              className={cn(
                'group flex flex-1 flex-col items-center gap-2 rounded-xl px-2 py-1.5 text-center transition',
                expandedId === step.id ? 'bg-slate-50' : 'hover:bg-slate-50/70',
              )}
            >
              <StepIcon step={step} />
              <div className="min-w-0">
                <div className={cn('text-sm font-semibold', STATUS_TEXT[step.status])}>{step.title}</div>
                {step.meta && <div className="truncate text-xs text-slate-400">{step.meta}</div>}
              </div>
            </button>
            {i < steps.length - 1 && (
              <div className="mx-1 h-0.5 w-full min-w-[24px] flex-1 rounded-full bg-slate-100">
                <div
                  className="h-full rounded-full bg-brand-gradient transition-[width] duration-500"
                  style={{ width: step.status === 'done' ? '100%' : '0%' }}
                />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Вертикальный список — mobile */}
      <div className="flex flex-col gap-2 p-5 lg:hidden">
        {steps.map((step) => (
          <button
            key={step.id}
            type="button"
            onClick={() => setExpandedId((v) => (v === step.id ? null : step.id))}
            className="flex items-center gap-3 rounded-xl border border-slate-100 p-3 text-left"
          >
            <StepIcon step={step} />
            <div className="min-w-0 flex-1">
              <div className={cn('text-sm font-semibold', STATUS_TEXT[step.status])}>{step.title}</div>
              {step.meta && <div className="truncate text-xs text-slate-400">{step.meta}</div>}
            </div>
            <StatusBadge step={step} />
          </button>
        ))}
      </div>

      {/* Progressive disclosure: деталь шага прямо на этом экране */}
      {expandedStep && (
        <div className="border-t border-slate-100 bg-slate-50/60 px-5 py-4">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-slate-800">{expandedStep.title}</span>
              <StatusBadge step={expandedStep} />
            </div>
            <div className="flex items-center gap-2">
              {expandedStep.action && (
                <button
                  type="button"
                  onClick={expandedStep.action.onClick}
                  disabled={expandedStep.status === 'blocked'}
                  className="btn-primary h-8 px-3 text-xs"
                  title={expandedStep.status === 'blocked' ? expandedStep.blockedReason : undefined}
                >
                  {expandedStep.action.label}
                </button>
              )}
              {onOpenFullScreen && (
                <button
                  type="button"
                  onClick={() => onOpenFullScreen(expandedStep.id)}
                  className="btn-ghost h-8 px-2 text-xs"
                >
                  Открыть полный экран
                  <ArrowRight className="h-3.5 w-3.5" />
                </button>
              )}
              <button
                type="button"
                onClick={() => setExpandedId(null)}
                className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-200/60"
                aria-label="Свернуть"
              >
                <ChevronDown className="h-4 w-4 rotate-180" />
              </button>
            </div>
          </div>

          {expandedStep.status === 'blocked' && expandedStep.blockedReason && (
            <p className="mb-2 flex items-center gap-1.5 text-xs text-slate-500">
              <Lock className="h-3.5 w-3.5" /> {expandedStep.blockedReason}
            </p>
          )}

          {expandedStep.detail}
        </div>
      )}

      {/* Next Best Action */}
      <div
        className={cn(
          'flex flex-wrap items-center justify-between gap-3 border-t px-5 py-4',
          allDone
            ? 'border-emerald-100 bg-emerald-50/60'
            : nextAction?.status === 'error'
              ? 'border-red-100 bg-red-50/60'
              : 'border-amber-100 bg-amber-50/60',
        )}
      >
        {allDone ? (
          <div className="flex items-center gap-2 text-sm font-semibold text-emerald-700">
            <CheckCircle2 className="h-4 w-4" />
            Рабочий день закрыт: все шаги выполнены, отчёт сформирован.
          </div>
        ) : nextAction ? (
          <>
            <div className="flex min-w-0 items-center gap-2 text-sm">
              <span className="font-semibold text-slate-800">Следующий шаг:</span>
              <span className="truncate text-slate-600">{nextAction.title}</span>
              {nextAction.meta && <span className="hidden truncate text-slate-400 sm:inline">· {nextAction.meta}</span>}
            </div>
            {nextAction.action && (
              <button type="button" onClick={nextAction.action.onClick} className="btn-primary h-9 shrink-0 px-4 text-sm">
                {nextAction.action.label}
                <ArrowRight className="h-4 w-4" />
              </button>
            )}
          </>
        ) : null}
      </div>
    </div>
  )
}
