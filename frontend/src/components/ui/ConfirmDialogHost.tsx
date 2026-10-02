import { useState } from 'react'
import { AlertTriangle, HelpCircle } from 'lucide-react'

import { cn } from '@/lib/cn'
import { useConfirmStore } from '@/lib/confirm'
import Modal from './Modal'

/**
 * Единственный экземпляр диалога подтверждения на всё приложение — монтируется
 * один раз в Layout.tsx. Слушает lib/confirm.ts и рисует запрос, если он есть.
 */
export default function ConfirmDialogHost() {
  const pending = useConfirmStore((s) => s.pending)
  const settle = useConfirmStore((s) => s.settle)
  const [comment, setComment] = useState('')

  const close = () => {
    setComment('')
    settle({ confirmed: false })
  }

  const confirmNow = () => {
    if (pending?.requireComment && !comment.trim()) return
    const value = comment.trim()
    setComment('')
    settle({ confirmed: true, comment: value || undefined })
  }

  const danger = pending?.tone === 'danger'
  const commentMissing = !!pending?.requireComment && !comment.trim()

  return (
    <Modal
      open={!!pending}
      onClose={close}
      size="sm"
      title={
        pending && (
          <span className="flex items-center gap-2">
            {danger ? <AlertTriangle className="h-5 w-5 text-red-500" /> : <HelpCircle className="h-5 w-5 text-emerald-600" />}
            {pending.title}
          </span>
        )
      }
      description={pending?.description}
      footer={
        pending && (
          <>
            <button type="button" onClick={close} className="btn-secondary">
              {pending.cancelLabel ?? 'Отмена'}
            </button>
            <button
              type="button"
              onClick={confirmNow}
              disabled={commentMissing}
              className={cn(danger ? 'btn-danger' : 'btn-primary')}
            >
              {pending.confirmLabel ?? (danger ? 'Подтвердить' : 'Продолжить')}
            </button>
          </>
        )
      }
    >
      {pending?.requireComment && (
        <div>
          <label className="label">{pending.requireComment}</label>
          <textarea
            className="input min-h-[84px] resize-none"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            autoFocus
            placeholder="Комментарий обязателен для этого действия"
          />
        </div>
      )}
    </Modal>
  )
}
