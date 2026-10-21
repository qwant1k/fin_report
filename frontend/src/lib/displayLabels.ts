type Labels = Readonly<Record<string, string>>

export const OPERATION_LABELS: Labels = {
  BUY: 'Покупка ценных бумаг',
  SELL: 'Продажа ценных бумаг',
  REPO: 'Операция РЕПО',
  REPO_OPEN: 'Открытие РЕПО',
  REPO_CLOSE: 'Закрытие РЕПО',
  COUPON: 'Выплата купона',
  REDEMPTION: 'Погашение ценных бумаг',
  DEPOSIT_OPEN: 'Размещение депозита',
  DEPOSIT_CLOSE: 'Возврат депозита',
  FX_BUY: 'Покупка валюты',
  FX_SELL: 'Продажа валюты',
  CASH_TOPUP: 'Пополнение денежных средств',
  CASH_WITHDRAW: 'Вывод денежных средств',
  RECEIPT: 'Поступление денежных средств',
  CONTRIBUTION: 'Взнос в портфель',
  INITIAL_BALANCE: 'Входящий остаток',
  PAYMENT: 'Списание денежных средств',
  WITHDRAWAL: 'Изъятие из портфеля',
  COMMISSION: 'Комиссия',
  CORRECTION: 'Корректировка',
  REPAYMENT: 'Погашение задолженности',
  WRITE_OFF: 'Списание задолженности',
  ADJUSTMENT: 'Корректировка задолженности',
  RECEIVABLE_CLOSE: 'Закрытие дебиторской задолженности',
  OTHER: 'Прочая операция',
}

export const CATEGORY_LABELS: Labels = {
  CASH: 'Денежные средства',
  GOV_BONDS: 'Государственные облигации',
  AGENCY_BONDS: 'Облигации квазигосударственного сектора',
  MFO_BONDS: 'Облигации международных финансовых организаций',
  FOREIGN_BONDS: 'Иностранные ценные бумаги',
  REVERSE_REPO: 'Обратное РЕПО',
  DEPOSIT: 'Депозиты',
  OTHER: 'Прочие активы',
}

export const WORKFLOW_STATUS_LABELS: Labels = {
  DRAFT: 'Черновик',
  PENDING: 'Ожидает обработки',
  PENDING_APPROVAL: 'На согласовании',
  APPROVED: 'Согласовано',
  REJECTED: 'Отклонено',
  PENDING_CANCELLATION: 'Аннулирование на согласовании',
  CANCELLED: 'Аннулировано',
}

export const RECEIVABLE_STATUS_LABELS: Labels = {
  OPEN: 'Открыта',
  PARTIAL: 'Частично погашена',
  CLOSED: 'Погашена',
  WRITTEN_OFF: 'Списана',
  OVERDUE: 'Просрочена',
}

export const PROCESS_STATUS_LABELS: Labels = {
  PENDING: 'Ожидает обработки',
  PROCESSING: 'Обрабатывается',
  PARSED: 'Распознан',
  IMPORTED: 'Импортирован',
  UPLOADED: 'Загружен',
  OK: 'Успешно',
  SUCCESS: 'Успешно',
  COMPLETED: 'Завершено',
  ERROR: 'Ошибка',
  FAILED: 'Не выполнено',
  SKIPPED: 'Пропущено',
  DUPLICATE: 'Дубликат',
  SUPERSEDED: 'Заменён новой версией',
  MATCHED: 'Совпадает',
  MISMATCH: 'Есть расхождения',
  WARNING: 'Требует внимания',
  ACTIVE: 'Активен',
  ARCHIVED: 'В архиве',
}

export const DOCUMENT_TYPE_LABELS: Labels = {
  TRADE_REPORT: 'Отчёт о сделках (Trade Report)',
  TRADE_REPORT_XLSX: 'Отчёт о сделках (Trade Report)',
  HOLDINGS: 'Портфель и остатки',
  HOLDINGS_XLSX: 'Портфель и остатки',
  CERTIFICATE: 'Биржевое свидетельство',
  CERTIFICATE_PDF: 'Биржевое свидетельство',
  CERTIFICATE_PNG: 'Биржевое свидетельство',
  CERTIFICATE_DOCX: 'Биржевое свидетельство',
  RECONCILIATION: 'Файл сверки',
  STATEMENT: 'Банковская выписка',
  STATEMENT_PDF: 'Банковская выписка',
  RISK_REPORT: 'Отчёт о рисках (Risk Report)',
  RISK_REPORT_XLSM: 'Отчёт о рисках (Risk Report)',
  NBRK_KFGD: 'Портфель Национального Банка',
  NBRK_DAILY: 'Ежедневные данные Национального Банка',
  TONIA_COMPOUNDED: 'Архив TONIA Compounded',
  OTHER: 'Прочий документ',
}

export const SOURCE_LABELS: Labels = {
  AUTO: 'Автоматически',
  MANUAL: 'Вручную',
  KASE: 'Данные KASE',
  KASE_MARKET: 'Рыночные данные KASE',
  EXTERNAL: 'Внешний источник',
  RISK_PARAMETERS: 'Риск-параметры KASE',
  SCHEDULER: 'Автоматическая загрузка',
  SCHEDULER_INITIAL: 'Первичная автоматическая загрузка',
  STATEMENT: 'Банковская выписка',
  NBRK_HTML: 'Сайт Национального Банка',
  KASE_XLSX: 'Файл KASE',
  KASE_API: 'Автоматическая загрузка KASE',
  KASE_GATEWAY: 'Шлюз KASE',
  RISK_REPORT: 'Отчёт о рисках',
  RISK_REPORT_XLSM: 'Отчёт о рисках',
  RISK_REPORT_CARRY: 'Последняя доступная цена из отчёта о рисках',
  MARKET: 'Рыночные данные KASE',
  PURCHASE: 'Цена покупки',
  AMORTIZED: 'Расчётная амортизированная цена',
  IMPORT: 'Загруженный файл',
  GENERATED: 'Рассчитано по параметрам',
  TRADE_REPORT_PENDING_ENRICHMENT: 'Отчёт о сделках — ожидаются данные KASE',
}

export const PORTFOLIO_TYPE_LABELS: Labels = {
  PRIVATE_CDU: 'Частные управляющие компании',
  NBRK_OWN: 'Собственные активы Национального Банка',
  NBRK_RESERVE: 'Специальный резерв Национального Банка',
}

export const REPORT_TYPE_LABELS: Labels = {
  DAILY: 'Ежедневный отчёт',
  DAILY_XLSX: 'Ежедневный отчёт Excel',
  DAILY_PDF: 'Ежедневный отчёт PDF',
  SUMMARY: 'Сводный отчёт',
  XLSX: 'Отчёт Excel',
  PDF: 'Отчёт PDF',
  RISK_REPORT: 'Отчёт о рисках',
  COMPLIANCE: 'Отчёт о соблюдении требований',
}

export const ALERT_SEVERITY_LABELS: Labels = {
  INFO: 'Информация',
  WARN: 'Предупреждение',
  WARNING: 'Предупреждение',
  CRITICAL: 'Критическое нарушение',
  ERROR: 'Ошибка',
}

export const ALERT_TYPE_LABELS: Labels = {
  LIMIT_BREACH: 'Нарушение лимита',
  DURATION_BREACH: 'Нарушение ограничения по дюрации',
  YTM_BREACH: 'Нарушение ограничения по доходности',
  CONCENTRATION_BREACH: 'Превышение концентрации',
  DATA_QUALITY: 'Проблема качества данных',
  MISSING_DATA: 'Недостаточно данных',
  CUSTOM_INDICATOR: 'Пользовательский индикатор',
  FIFO_SHORTFALL: 'Недостаток позиции по методу ФИФО',
  VALUATION_WARNINGS: 'Предупреждение при оценке',
  AR_MISMATCH: 'Расхождение по дебиторской задолженности',
  RECON_SECURITIES: 'Расхождение при сверке ценных бумаг',
  RECON_CASH: 'Расхождение при сверке денежных средств',
  RECON_REPO: 'Расхождение при сверке РЕПО',
}

export const COUPON_TYPE_LABELS: Labels = {
  FIX: 'Фиксированный',
  FIXED: 'Фиксированный',
  FLOAT: 'Плавающий',
  FLOATING: 'Плавающий',
  ZERO: 'Дисконтный',
}

export const AUDIT_ACTION_LABELS: Labels = {
  CREATE: 'Создание',
  UPDATE: 'Изменение',
  DELETE: 'Удаление',
  IMPORT: 'Импорт данных',
  UPLOAD: 'Загрузка файла',
  DOWNLOAD: 'Скачивание файла',
  APPROVE: 'Согласование',
  REJECT: 'Отклонение',
  CANCEL: 'Аннулирование',
  LOGIN: 'Вход в систему',
  LOGOUT: 'Выход из системы',
  GENERATE: 'Формирование отчёта',
}

export const ENTITY_LABELS: Labels = {
  TRADE: 'Сделка',
  CASH_MOVEMENT: 'Денежное движение',
  RECEIVABLE: 'Дебиторская задолженность',
  DOCUMENT: 'Документ',
  REPORT: 'Отчёт',
  USER: 'Пользователь',
  ROLE: 'Роль',
  PERMISSION: 'Право доступа',
  SECURITY: 'Ценная бумага',
  INDICATOR: 'Индикатор',
  SETTING: 'Настройка',
}

export const FIELD_LABELS: Labels = {
  AMOUNT: 'Сумма', AMOUNT_KZT: 'Сумма, ₸', VALUE: 'Стоимость', DELTA: 'Отклонение',
  DELTA_VALUE: 'Отклонение стоимости', EXPECTED: 'Расчётное значение', ACTUAL: 'Фактическое значение',
  COUNT: 'Количество', QUANTITY: 'Количество бумаг', FACE_VALUE: 'Номинальная стоимость',
  PRICE: 'Цена', MARKET_PRICE: 'Рыночная цена', ACCRUED: 'Накопленное вознаграждение',
  STATUS: 'Статус', DATE: 'Дата', OPEN_DATE: 'Дата открытия', CLOSE_DATE: 'Дата закрытия',
  CURRENCY: 'Валюта', SOURCE: 'Источник', ISIN: 'ISIN', TICKER: 'Тикер', NAME: 'Наименование',
  DEAL_ID: 'Номер сделки', LOTS: 'Количество лотов', RATE_PCT: 'Ставка, %', NOTE: 'Примечание',
  OURS: 'По данным системы', CDU: 'По данным ЧДУ', DIFFERENCE: 'Расхождение',
}

const TOKEN_LABELS: Labels = {
  OPEN: 'открытие', CLOSE: 'закрытие', CLOSED: 'закрыто', BUY: 'покупка', SELL: 'продажа',
  CREATE: 'создание', UPDATE: 'изменение', DELETE: 'удаление', IMPORT: 'импорт', EXPORT: 'экспорт',
  APPROVE: 'согласование', APPROVED: 'согласовано', REJECT: 'отклонение', REJECTED: 'отклонено',
  PENDING: 'ожидает', CANCEL: 'аннулирование', CANCELLED: 'аннулировано', MANUAL: 'вручную', AUTO: 'автоматически',
  REPORT: 'отчёт', DOCUMENT: 'документ', TRADE: 'сделка', CASH: 'денежные средства', MOVEMENT: 'движение',
  RECEIVABLE: 'дебиторская задолженность', SECURITY: 'ценная бумага', OTHER: 'прочее', ERROR: 'ошибка',
}

function key(value: unknown) {
  return String(value ?? '').trim().replace(/[.-]/g, '_').toUpperCase()
}

/** Не допускает вывода внутренних значений вроде REPO_CLOSE в пользовательский интерфейс. */
export function labelFrom(value: unknown, labels: Labels): string {
  const raw = String(value ?? '').trim()
  if (!raw) return '—'
  const normalized = key(raw)
  const direct = labels[normalized]
  if (direct) return direct

  const translated = normalized.split('_').map((token) => TOKEN_LABELS[token] ?? token).join(' ')
  return translated.charAt(0).toUpperCase() + translated.slice(1).toLowerCase()
}

export const operationLabel = (value: unknown) => labelFrom(value, OPERATION_LABELS)
export const categoryLabel = (value: unknown) => labelFrom(value, CATEGORY_LABELS)
export const workflowStatusLabel = (value: unknown) => labelFrom(value, WORKFLOW_STATUS_LABELS)
export const receivableStatusLabel = (value: unknown) => labelFrom(value, RECEIVABLE_STATUS_LABELS)
export const processStatusLabel = (value: unknown) => labelFrom(value, PROCESS_STATUS_LABELS)
export const documentTypeLabel = (value: unknown) => labelFrom(value, DOCUMENT_TYPE_LABELS)
export const sourceLabel = (value: unknown) => labelFrom(value, SOURCE_LABELS)
export const portfolioTypeLabel = (value: unknown) => labelFrom(value, PORTFOLIO_TYPE_LABELS)
export const reportTypeLabel = (value: unknown) => labelFrom(value, REPORT_TYPE_LABELS)
export const alertSeverityLabel = (value: unknown) => labelFrom(value, ALERT_SEVERITY_LABELS)
export const alertTypeLabel = (value: unknown) => labelFrom(value, ALERT_TYPE_LABELS)
export const couponTypeLabel = (value: unknown) => labelFrom(value, COUPON_TYPE_LABELS)
export const auditActionLabel = (value: unknown) => labelFrom(value, AUDIT_ACTION_LABELS)
export const entityLabel = (value: unknown) => labelFrom(value, ENTITY_LABELS)
export const fieldLabel = (value: unknown) => labelFrom(value, FIELD_LABELS)

const TECHNICAL_TEXT_REPLACEMENTS: ReadonlyArray<readonly [RegExp, string]> = [
  [/по данным Risk Report/gi, 'по данным отчёта о рисках'],
  [/Risk Report/gi, 'отчёт о рисках'],
  [/Trade Report|TradeReport/gi, 'отчёт о сделках'],
  [/REPO_CLOSE/g, 'закрытие РЕПО'],
  [/REPO_OPEN/g, 'открытие РЕПО'],
  [/REVERSE_REPO/g, 'обратное РЕПО'],
  [/DEPOSIT_CLOSE/g, 'возврат депозита'],
  [/DEPOSIT_OPEN/g, 'размещение депозита'],
  [/FX_BUY/g, 'покупка валюты'],
  [/FX_SELL/g, 'продажа валюты'],
  [/\bCash\b/gi, 'Денежные средства'],
  [/\bREPO\b/g, 'РЕПО'],
  [/\bFIFO\b/g, 'ФИФО'],
]

/** Переводит технические обозначения, встроенные сервером в свободный текст. */
export function localizeTechnicalText(value: unknown): string {
  return TECHNICAL_TEXT_REPLACEMENTS.reduce(
    (text, [pattern, replacement]) => text.replace(pattern, replacement),
    String(value ?? ''),
  )
}
