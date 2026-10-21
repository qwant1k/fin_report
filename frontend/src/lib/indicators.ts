import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

/** Пользовательские показатели (раздел «Формулы → Мои показатели»). */

export type IndicatorUnit = 'KZT' | 'PCT' | 'NUMBER' | 'DAYS'
export type IndicatorLevel = 'cdu' | 'fund'

export const UNIT_LABEL: Record<IndicatorUnit, string> = {
  KZT: 'тенге, ₸',
  PCT: 'проценты, %',
  NUMBER: 'число',
  DAYS: 'дни',
}

export const ALERT_OPS: Array<{ value: string; label: string }> = [
  { value: '>', label: 'больше' },
  { value: '<', label: 'меньше' },
  { value: '>=', label: 'не меньше' },
  { value: '<=', label: 'не больше' },
]

export interface IndicatorValue {
  id: number
  name: string
  unit: IndicatorUnit
  decimals: number
  value: number | null
  alert: boolean
  substituted: string
  formula: string
}

export interface IndicatorValues {
  date: string
  indicators: Array<{ id: number; name: string; unit: IndicatorUnit; level: IndicatorLevel; decimals: number; description: string | null }>
  by_cdu: Record<string, IndicatorValue[]>
  fund: IndicatorValue[]
}

export function formatIndicator(value: number | null | undefined, unit: IndicatorUnit, decimals = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const s = value.toLocaleString('ru-RU', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
  if (unit === 'PCT') return `${s} %`
  if (unit === 'KZT') return `${s} ₸`
  if (unit === 'DAYS') return `${s} дн.`
  return s
}

export function useIndicatorValues(date: string | null | undefined) {
  return useQuery<IndicatorValues>({
    queryKey: ['indicator-values', date],
    enabled: !!date,
    staleTime: 30_000,
    queryFn: async () => (await api.get('/formulas/indicators/values', { params: { date } })).data,
  })
}

export function breached(op: string | null | undefined, threshold: number | null | undefined, value: number | null): boolean {
  if (value === null || value === undefined || !op || threshold === null || threshold === undefined) return false
  if (op === '>') return value > threshold
  if (op === '<') return value < threshold
  if (op === '>=') return value >= threshold
  if (op === '<=') return value <= threshold
  return false
}
