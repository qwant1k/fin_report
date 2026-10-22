import type { AlertItem } from '@/lib/types'

export const ALERT_STATUS_LABELS: Record<AlertItem['status'], string> = {
  NEW: 'Новое',
  IN_PROGRESS: 'В работе',
  RESOLVED: 'Решено',
}

export const ALERT_DETAIL_LABELS: Record<string, string> = {
  category_name: 'Категория',
  actual_pct: 'Фактическая доля',
  minimum_pct: 'Минимум',
  maximum_pct: 'Допустимый максимум',
  deviation_pct_points: 'Превышение',
  limit_kind: 'Вид лимита',
  actual_duration: 'Фактическая дюрация',
  minimum_duration: 'Нижняя граница',
  maximum_duration: 'Верхняя граница',
  benchmark_duration: 'Ориентир MBM',
  value: 'Фактическое значение',
  threshold: 'Порог',
  received: 'Поступило',
  expected: 'Ожидалось',
  deviation: 'Отклонение',
  warning_count: 'Количество замечаний',
  isin: 'Ценная бумага',
}

const PERCENT_KEYS = new Set(['actual_pct', 'minimum_pct', 'maximum_pct', 'deviation_pct_points'])
const MONEY_KEYS = new Set(['received', 'expected', 'deviation'])
const DURATION_KEYS = new Set(['actual_duration', 'minimum_duration', 'maximum_duration', 'benchmark_duration'])

export function alertDetailValue(key: string, value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'number') {
    const formatted = value.toLocaleString('ru-KZ', { maximumFractionDigits: DURATION_KEYS.has(key) ? 3 : 2 })
    if (PERCENT_KEYS.has(key)) return `${formatted}%`
    if (MONEY_KEYS.has(key)) return `${formatted} ₸`
    return formatted
  }
  return String(value)
}

export function visibleAlertDetails(details: Record<string, unknown>) {
  return Object.entries(details).filter(([key, value]) =>
    key in ALERT_DETAIL_LABELS && value != null && !Array.isArray(value) && typeof value !== 'object',
  )
}
