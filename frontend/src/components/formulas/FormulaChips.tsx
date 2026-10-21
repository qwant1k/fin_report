import { Fragment } from 'react'
import clsx from 'clsx'

/** Визуальная запись формулы: поля — цветные «плашки», параметры — жёлтые, функции — фиолетовые. */

export interface Token { t: 'field' | 'op' | 'num' | 'param' | 'fn' | 'text'; v: string; code?: string }

export function FieldChip({ name, small, onClick, draggable, title }: {
  name: string; small?: boolean; onClick?: () => void; draggable?: boolean; title?: string
}) {
  const Tag = onClick ? 'button' : 'span'
  return (
    <Tag
      type={onClick ? 'button' : undefined}
      title={title}
      onClick={onClick}
      draggable={draggable}
      onDragStart={draggable ? (e: React.DragEvent) => {
        e.dataTransfer.setData('text/plain', `[${name}]`)
        e.dataTransfer.effectAllowed = 'copy'
      } : undefined}
      className={clsx(
        'inline-flex items-center rounded-md bg-sky-50 font-medium text-sky-800 ring-1 ring-inset ring-sky-600/20',
        small ? 'px-1.5 py-0 text-[12px]' : 'px-2 py-0.5 text-[13px]',
        onClick && 'cursor-pointer transition hover:bg-sky-100 hover:ring-sky-600/40',
        draggable && 'cursor-grab active:cursor-grabbing',
      )}
    >
      {name}
    </Tag>
  )
}

export function ParamChip({ label, value, onClick }: { label: string; value?: string; onClick?: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title="Параметр расчёта — можно изменить во вкладке «Параметры расчёта»"
      className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-0.5 text-[13px] font-medium text-amber-900 ring-1 ring-inset ring-amber-600/30 transition hover:bg-amber-100"
    >
      {label}{value !== undefined && <span className="font-semibold tabular-nums">= {value}</span>}
    </button>
  )
}

export function TokenFormula({ tokens, params, onParam }: {
  tokens: Token[]; params?: Record<string, string>; onParam?: (code: string) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1.5 leading-7">
      {tokens.map((t, i) => {
        if (t.t === 'field') return <FieldChip key={i} name={t.v} />
        if (t.t === 'param') return <ParamChip key={i} label={t.v} value={t.code ? params?.[t.code] : undefined}
          onClick={t.code && onParam ? () => onParam(t.code!) : undefined} />
        if (t.t === 'fn') return <span key={i} className="font-semibold text-violet-700">{t.v}</span>
        if (t.t === 'num') return <span key={i} className="font-mono text-[13px] text-slate-800">{t.v}</span>
        if (t.t === 'text') return <span key={i} className="text-xs italic text-slate-500">{t.v}</span>
        return <span key={i} className="px-0.5 text-base font-bold text-slate-500">{t.v}</span>
      })}
    </div>
  )
}

/** Текст формулы пользователя → цветная запись: [Поле] как плашки, ФУНКЦИЯ( фиолетовым. */
export function PrettyFormula({ text, className }: { text: string; className?: string }) {
  const parts = text.split(/(\[[^\]]+\])/g)
  return (
    <span className={clsx('leading-7', className)}>
      {parts.map((p, i) => {
        if (p.startsWith('[') && p.endsWith(']')) return <Fragment key={i}><FieldChip name={p.slice(1, -1)} small /> </Fragment>
        const sub = p.split(/([А-ЯЁA-Z]{2,}(?=\())/g)
        return (
          <Fragment key={i}>
            {sub.map((s, j) => (/^[А-ЯЁA-Z]{2,}$/.test(s)
              ? <span key={j} className="font-semibold text-violet-700">{s}</span>
              : <span key={j} className="text-slate-700">{s}</span>))}
          </Fragment>
        )
      })}
    </span>
  )
}
