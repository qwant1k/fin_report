import axios from 'axios'

import { localizeTechnicalText } from './displayLabels'

const FIELD_NAMES: ReadonlyArray<readonly [RegExp, string]> = [
  [/\btrade_date\b/gi, 'дата сделки'],
  [/\binstrument_code\b/gi, 'код инструмента'],
  [/\binstrument_category\b/gi, 'категория инструмента'],
  [/\breport_date\b/gi, 'дата отчёта'],
  [/\bdoc_date\b/gi, 'дата документа'],
  [/\bstart_date\b/gi, 'дата начала'],
  [/\bend_date\b/gi, 'дата окончания'],
  [/\bfolder_path\b/gi, 'путь к папке'],
  [/\bfield_key\b/gi, 'поле отчёта'],
  [/\bexpression_json\b/gi, 'формула'],
  [/\bImportJob\b/g, 'Задача импорта'],
  [/\bjob\s*#/gi, 'задача №'],
  [/\bid\s*=\s*/gi, '№'],
]

const ENGLISH_PHRASES: ReadonlyArray<readonly [RegExp, string]> = [
  [/trade_date and instrument_code are required/gi, 'Укажите дату сделки и код инструмента'],
  [/is required/gi, 'обязательно для заполнения'],
  [/not found/gi, 'не найдено'],
  [/network error/gi, 'Нет связи с сервером'],
  [/timeout of \d+ms exceeded/gi, 'Сервер не ответил вовремя'],
]

function cleanText(value: unknown): string {
  let text = localizeTechnicalText(value).replace(/\s+/g, ' ').trim()
  for (const [pattern, replacement] of FIELD_NAMES) text = text.replace(pattern, replacement)
  for (const [pattern, replacement] of ENGLISH_PHRASES) text = text.replace(pattern, replacement)
  return text
}

function short(text: string, max = 320): string {
  if (text.length <= max) return text
  return `${text.slice(0, max - 1).trimEnd()}…`
}

function detailText(detail: unknown): string {
  if (typeof detail === 'string') return cleanText(detail)
  if (Array.isArray(detail)) {
    const messages = detail.map((item: any) => {
      const location = Array.isArray(item?.loc) ? item.loc.filter((part: unknown) => part !== 'body').join('.') : ''
      const message = item?.msg ?? item?.message ?? item
      return cleanText(location ? `${location}: ${message}` : message)
    }).filter(Boolean)
    return messages.join('; ')
  }
  if (detail && typeof detail === 'object') {
    const value = detail as Record<string, unknown>
    return detailText(value.message ?? value.detail ?? value.reason ?? value.error)
  }
  return ''
}

function withPeriod(text: string): string {
  return /[.!?…]$/.test(text) ? text : `${text}.`
}

/** Короткое русское сообщение об ошибке с контекстом пользовательского действия. */
export function apiErrorMessage(error: unknown, fallback: string): string {
  const base = withPeriod(cleanText(fallback))
  if (!axios.isAxiosError(error)) {
    const reason = error instanceof Error ? cleanText(error.message) : ''
    return short(reason && reason !== fallback ? `${base} Причина: ${withPeriod(reason)}` : base)
  }

  if (error.code === 'ECONNABORTED') return `${base} Сервер не ответил вовремя; повторите попытку.`
  if (!error.response) return `${base} Нет связи с сервером; проверьте подключение и повторите попытку.`

  const status = error.response.status
  const reason = detailText((error.response.data as any)?.detail)
  if (reason) {
    const normalizedReason = withPeriod(reason)
    if (normalizedReason.toLocaleLowerCase('ru').startsWith(base.toLocaleLowerCase('ru').replace(/[.!?…]$/, ''))) {
      return short(normalizedReason)
    }
    return short(`${base} Причина: ${normalizedReason}`)
  }

  const statusReason: Record<number, string> = {
    400: 'Проверьте заполненные данные.',
    403: 'Недостаточно прав для этого действия.',
    404: 'Запрашиваемая запись не найдена.',
    409: 'Действие конфликтует с текущим состоянием записи.',
    413: 'Файл слишком большой.',
    422: 'Проверьте обязательные поля и формат значений.',
    429: 'Слишком много запросов; повторите немного позже.',
  }
  return short(`${base} ${statusReason[status] ?? (status >= 500 ? 'Сервер временно не может выполнить запрос; повторите позже.' : `Код ответа: ${status}.`)}`)
}

export function notificationText(value: unknown, fallback: string): string {
  const text = detailText(value) || cleanText(fallback)
  return short(withPeriod(text))
}
