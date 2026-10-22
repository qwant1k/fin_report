import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertOctagon, AlertTriangle, CheckCircle2, ChevronDown, ChevronUp,
  CircleDot, ExternalLink, Info, UserRoundCheck,
} from 'lucide-react'

import type { AlertItem } from '@/lib/types'
import { formatDate } from '@/lib/format'
import { alertSeverityLabel, alertTypeLabel, localizeTechnicalText } from '@/lib/displayLabels'
import { ALERT_DETAIL_LABELS, ALERT_STATUS_LABELS, alertDetailValue, visibleAlertDetails } from '@/lib/alerts'
import { cn } from '@/lib/cn'

const severityStyle = {
  INFO: { icon: Info, border: 'border-blue-200', tint: 'bg-blue-50/70', text: 'text-blue-700' },
  WARN: { icon: AlertTriangle, border: 'border-amber-200', tint: 'bg-amber-50/70', text: 'text-amber-700' },
  CRITICAL: { icon: AlertOctagon, border: 'border-rose-200', tint: 'bg-rose-50/70', text: 'text-rose-700' },
}

interface Props {
  alert: AlertItem
  compact?: boolean
  busy?: boolean
  onTake?: (alert: AlertItem) => void
  onResolve?: (alert: AlertItem) => void
  onNavigate?: () => void
}

export default function AlertControlCard({ alert, compact = false, busy, onTake, onResolve, onNavigate }: Props) {
  const [expanded, setExpanded] = useState(false)
  const tone = severityStyle[alert.severity]
  const Icon = tone.icon
  const details = visibleAlertDetails(alert.details ?? {})
  const explanation = typeof alert.details?.explanation === 'string' ? alert.details.explanation : null
  const warnings = Array.isArray(alert.details?.warnings) ? alert.details.warnings.map(String) : []
  const problems = Array.isArray(alert.details?.problems) ? alert.details.problems.map(String) : []
  const hasExplanation = details.length > 0 || !!explanation || warnings.length > 0 || problems.length > 0

  return (
    <article className={cn('rounded-xl border bg-white shadow-sm', tone.border, alert.status === 'RESOLVED' && 'opacity-75')}>
      <div className={cn('rounded-t-xl border-b px-4 py-3', tone.border, tone.tint)}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2.5">
            <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', tone.text)} />
            <div className="min-w-0">
              <div className={cn('text-[11px] font-bold uppercase tracking-wide', tone.text)}>
                {alertTypeLabel(alert.alert_type)} · {alertSeverityLabel(alert.severity)}
              </div>
              <h3 className={cn('mt-0.5 font-semibold leading-snug text-slate-900', compact ? 'text-sm' : 'text-base')}>
                {localizeTechnicalText(alert.message)}
              </h3>
            </div>
          </div>
          <span className={cn(
            'inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-1 text-[10px] font-bold',
            alert.status === 'NEW' && 'bg-white text-slate-700 ring-1 ring-slate-200',
            alert.status === 'IN_PROGRESS' && 'bg-indigo-100 text-indigo-700',
            alert.status === 'RESOLVED' && 'bg-emerald-100 text-emerald-700',
          )}>
            {alert.status === 'NEW' && <CircleDot className="h-3 w-3" />}
            {alert.status === 'IN_PROGRESS' && <UserRoundCheck className="h-3 w-3" />}
            {alert.status === 'RESOLVED' && <CheckCircle2 className="h-3 w-3" />}
            {ALERT_STATUS_LABELS[alert.status]}
          </span>
        </div>
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
          <span>{formatDate(alert.alert_date)}</span>
          <span>{alert.cdu_short_name || alert.cdu_name || 'По фонду'}</span>
          {alert.assigned_to && <span>Ответственный: {alert.assigned_to}</span>}
        </div>
      </div>

      <div className="px-4 py-3">
        {hasExplanation && (
          <>
            <button type="button" onClick={() => setExpanded((value) => !value)} className="flex items-center gap-1 text-xs font-semibold text-slate-600 hover:text-slate-900">
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
              Почему возникло
            </button>
            {expanded && (
              <div className="mt-3 rounded-lg bg-slate-50 p-3">
                {explanation && <p className="mb-2 text-xs leading-relaxed text-slate-600">{explanation}</p>}
                {details.length > 0 && (
                  <dl className="grid grid-cols-1 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-2">
                    {details.map(([key, value]) => (
                      <div key={key} className="flex justify-between gap-3 border-b border-slate-200/70 py-1">
                        <dt className="text-slate-500">{ALERT_DETAIL_LABELS[key]}</dt>
                        <dd className="text-right font-semibold text-slate-800">{alertDetailValue(key, value)}</dd>
                      </div>
                    ))}
                  </dl>
                )}
                {[...warnings, ...problems].slice(0, compact ? 3 : 10).map((item) => (
                  <div key={item} className="mt-1.5 flex gap-2 text-xs text-slate-600"><span>•</span><span>{localizeTechnicalText(item)}</span></div>
                ))}
              </div>
            )}
          </>
        )}

        {alert.status === 'RESOLVED' && (alert.resolved_by || alert.resolution_comment) && (
          <div className="mt-3 rounded-lg border border-emerald-100 bg-emerald-50/60 px-3 py-2 text-xs text-emerald-800">
            Решено{alert.resolved_by ? `: ${alert.resolved_by}` : ''}{alert.resolution_comment ? ` — ${alert.resolution_comment}` : ''}
          </div>
        )}

        <div className="mt-3 flex flex-wrap justify-end gap-2">
          {alert.action_path && (
            <Link to={alert.action_path} onClick={onNavigate} className="btn-secondary h-8 px-3 text-xs">
              <ExternalLink className="h-3.5 w-3.5" /> {alert.action_label || 'Открыть источник'}
            </Link>
          )}
          {alert.status === 'NEW' && onTake && (
            <button type="button" disabled={busy} onClick={() => onTake(alert)} className="btn-secondary h-8 px-3 text-xs text-indigo-700">
              <UserRoundCheck className="h-3.5 w-3.5" /> Взять в работу
            </button>
          )}
          {alert.status !== 'RESOLVED' && onResolve && (
            <button type="button" disabled={busy} onClick={() => onResolve(alert)} className="btn-primary h-8 px-3 text-xs">
              <CheckCircle2 className="h-3.5 w-3.5" /> Отметить решённым
            </button>
          )}
        </div>
      </div>
    </article>
  )
}
