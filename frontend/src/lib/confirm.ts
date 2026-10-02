import type { ReactNode } from 'react'
import { create } from 'zustand'

export interface ConfirmOptions {
  title: string
  description?: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  /** 'danger' — красная кнопка подтверждения (удаление, отклонение, аннулирование). */
  tone?: 'danger' | 'default'
  /** Если задано — под описанием появляется обязательное текстовое поле (причина/комментарий). */
  requireComment?: string | false
}

export interface ConfirmResult {
  confirmed: boolean
  comment?: string
}

interface PendingConfirm extends ConfirmOptions {
  resolve: (result: ConfirmResult) => void
}

interface ConfirmState {
  pending: PendingConfirm | null
  ask: (options: ConfirmOptions) => Promise<ConfirmResult>
  settle: (result: ConfirmResult) => void
}

/**
 * Единая точка подтверждения критичных действий (см. UX-аудит, п.5 "недостаточно
 * доверия к критическим операциям"): раньше в разных местах приложения были вперемешку
 * window.confirm/window.prompt, собственные inline-модалки, а где-то подтверждения не
 * было вовсе (удаление ЧДУ, пользователя, роли). Теперь один вызов на всё приложение:
 *
 *   const confirm = useConfirm()
 *   const { confirmed } = await confirm({ title: '...', tone: 'danger' })
 *   if (confirmed) mutate()
 */
export const useConfirmStore = create<ConfirmState>((set) => ({
  pending: null,
  ask: (options) =>
    new Promise<ConfirmResult>((resolve) => {
      set({ pending: { ...options, resolve } })
    }),
  settle: (result) =>
    set((state) => {
      state.pending?.resolve(result)
      return { pending: null }
    }),
}))

export function useConfirm() {
  return useConfirmStore((s) => s.ask)
}
