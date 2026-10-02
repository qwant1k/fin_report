import { create } from 'zustand'

export function todayIso(): string {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 10)
}

interface WorkContextState {
  /** Единая рабочая дата, разделяемая между Рабочим днём, Позициями, KASE, Сверкой и Отчётами. */
  workDate: string
  setWorkDate: (date: string) => void
  shiftWorkDate: (days: number) => void
}

/**
 * Глобальный контекст рабочего дня (см. UX-аудит, п.1 "раздробленный процесс"):
 * раньше дата выбиралась локально на каждом экране, из-за чего пользователь мог
 * загрузить данные за одну дату, а сформировать отчёт за другую. Теперь дата
 * живёт в одном сторе и переживает переход между страницами SPA.
 */
export const useWorkContextStore = create<WorkContextState>((set, get) => ({
  workDate: todayIso(),
  setWorkDate: (date) => set({ workDate: date || todayIso() }),
  shiftWorkDate: (days) => {
    const d = new Date(get().workDate || todayIso())
    d.setDate(d.getDate() + days)
    set({ workDate: d.toISOString().slice(0, 10) })
  },
}))
