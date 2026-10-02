import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { useWorkContextStore } from '@/lib/workContext'
import { Table2, Calendar, Building2 } from 'lucide-react'

interface PositionRow {
  cdu_id: number
  cdu_name: string
  isin: string
  instrument_category: string | null
  instrument_code: string | null
  description: string | null
  net_quantity: number
  net_face_value: number
  last_trade_date: string | null
  price?: number | null
  price_source?: string | null
  accrued_interest?: number | null
  market_value?: number | null
  ytm?: number | null
  duration?: number | null
  lots?: number
}

const PRICE_SOURCE_LABEL: Record<string, string> = {
  risk_report: 'Risk Report',
  market: 'KASE рынок',
  risk_parameters: 'KASE риск-параметры',
  market_stale: 'KASE (старая дата)',
  risk_parameters_stale: 'Риск-параметры (старая дата)',
  risk_report_carry: 'цена RR (нет KASE)',
  purchase: 'цена покупки',
  par: 'номинал',
  par_matured: 'погашена — номинал',
  trade: 'сделка',
  manual: 'ручная',
}

const fmt = (v: number | null | undefined, digits = 2) =>
  v == null ? '—' : v.toLocaleString('ru-KZ', { minimumFractionDigits: digits, maximumFractionDigits: digits })

interface PositionsResponse {
  as_of_date: string
  cdu_id: number | null
  last_update_date: string | null
  rows: PositionRow[]
  base_dates?: Record<string, string>
  warnings?: string[]
}

interface CDUOption {
  id: number
  name: string
}

export default function PositionsPage() {
  // Общая рабочая дата (см. lib/workContext.ts) — синхронизирована с Рабочим днём,
  // KASE, Сверкой и Отчётами, чтобы не пришлось выставлять дату заново на каждом экране.
  const asOfDate = useWorkContextStore((s) => s.workDate)
  const setAsOfDate = useWorkContextStore((s) => s.setWorkDate)
  const [cduId, setCduId] = useState<string>('')
  const [cdus, setCdus] = useState<CDUOption[]>([])
  const [data, setData] = useState<PositionsResponse | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.get('/settings/cdus').then((r) => setCdus(r.data)).catch(() => {})
  }, [])

  const fetchPositions = async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = { as_of: asOfDate }
      if (cduId) params.cdu_id = cduId
      const res = await api.get<PositionsResponse>('/positions/as-of', { params })
      setData(res.data)
    } catch {
      alert('Ошибка загрузки позиций')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchPositions()
  }, [asOfDate, cduId])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
          <Table2 className="w-6 h-6 text-emerald-600" />
          Позиции на дату
        </h1>
        <div className="flex items-center gap-3">
          {data?.last_update_date && (
            <span className="text-xs bg-amber-50 text-amber-700 border border-amber-200 px-2 py-1 rounded">
              Последнее изменение: {data.last_update_date}
            </span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-4 bg-white p-4 rounded-lg shadow-sm border border-slate-200">
        <div className="flex items-center gap-2">
          <Calendar className="w-4 h-4 text-slate-400" />
          <label className="text-sm text-slate-600">Состояние на</label>
          <input
            type="date"
            value={asOfDate}
            onChange={(e) => setAsOfDate(e.target.value)}
            className="border border-slate-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
        </div>
        <div className="flex items-center gap-2">
          <Building2 className="w-4 h-4 text-slate-400" />
          <label className="text-sm text-slate-600">ЧДУ</label>
          <select
            value={cduId}
            onChange={(e) => setCduId(e.target.value)}
            className="border border-slate-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 min-w-[180px]"
          >
            <option value="">Все ЧДУ</option>
            {cdus.map((c) => (
              <option key={c.id} value={String(c.id)}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        {loading && <span className="text-sm text-slate-400">Загрузка…</span>}
      </div>

      {data && (
        <div className="bg-white rounded-lg shadow-sm border border-slate-200 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <div className="text-sm text-slate-500">
              Данные актуальны на <strong>{data.as_of_date}</strong>
              {data.last_update_date && data.last_update_date !== data.as_of_date && (
                <span className="ml-2 text-amber-600">
                  (последнее обновление: {data.last_update_date})
                </span>
              )}
            </div>
            <div className="text-sm text-slate-500">{data.rows.length} позиций</div>
          </div>
          {data.base_dates && Object.keys(data.base_dates).length > 0 && (
            <div className="px-4 py-2 text-xs text-slate-500 border-b border-slate-100">
              База (последний Risk Report):{' '}
              {Object.entries(data.base_dates).map(([k, v]) => `${k} — ${v}`).join('; ')}.
              Далее позиции перенесены операциями Trades и переоценены на выбранную дату.
            </div>
          )}
          {data.warnings && data.warnings.length > 0 && (
            <details className="px-4 py-2 text-xs text-amber-700 bg-amber-50 border-b border-amber-100">
              <summary className="cursor-pointer">Предупреждения оценки: {data.warnings.length}</summary>
              <ul className="mt-1 list-disc pl-5 space-y-0.5">
                {data.warnings.slice(0, 100).map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </details>
          )}
          <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left text-slate-600 font-medium">ЧДУ</th>
                <th className="px-3 py-2 text-left text-slate-600 font-medium">ISIN</th>
                <th className="px-3 py-2 text-left text-slate-600 font-medium">Категория</th>
                <th className="px-3 py-2 text-left text-slate-600 font-medium">Код</th>
                <th className="px-3 py-2 text-right text-slate-600 font-medium">Кол-во</th>
                <th className="px-3 py-2 text-right text-slate-600 font-medium">Номинал</th>
                <th className="px-3 py-2 text-right text-slate-600 font-medium">Цена, %</th>
                <th className="px-3 py-2 text-right text-slate-600 font-medium">НКД</th>
                <th className="px-3 py-2 text-right text-slate-600 font-medium">Стоимость, KZT</th>
                <th className="px-3 py-2 text-right text-slate-600 font-medium">YTM</th>
                <th className="px-3 py-2 text-right text-slate-600 font-medium">Mod. дюрация</th>
                <th className="px-3 py-2 text-left text-slate-600 font-medium">Источник цены</th>
                <th className="px-3 py-2 text-left text-slate-600 font-medium">Дата покупки/открытия</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={`${r.cdu_id}-${r.instrument_category}-${r.isin}-${r.instrument_code ?? ''}`} className="border-t hover:bg-slate-50">
                  <td className="px-3 py-2">{r.cdu_name}</td>
                  <td className="px-3 py-2 font-mono text-xs" title={r.description ?? undefined}>{r.isin}</td>
                  <td className="px-3 py-2">{r.instrument_category ?? '-'}</td>
                  <td className="px-3 py-2">{r.instrument_code ?? '-'}</td>
                  <td className="px-3 py-2 text-right">{r.net_quantity ? fmt(r.net_quantity, 0) : '—'}</td>
                  <td className="px-3 py-2 text-right">{fmt(r.net_face_value)}</td>
                  <td className="px-3 py-2 text-right">{fmt(r.price, 4)}</td>
                  <td className="px-3 py-2 text-right">{fmt(r.accrued_interest)}</td>
                  <td className="px-3 py-2 text-right font-medium">{fmt(r.market_value)}</td>
                  <td className="px-3 py-2 text-right">{r.ytm == null ? '—' : `${(r.ytm * 100).toFixed(2)}%`}</td>
                  <td className="px-3 py-2 text-right">{fmt(r.duration, 3)}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">
                    {r.price_source ? PRICE_SOURCE_LABEL[r.price_source] ?? r.price_source : '—'}
                    {r.lots && r.lots > 1 ? ` · ${r.lots} лота` : ''}
                  </td>
                  <td className="px-3 py-2">{r.last_trade_date ?? '-'}</td>
                </tr>
              ))}
              {data.rows.length === 0 && (
                <tr>
                  <td colSpan={13} className="px-4 py-6 text-center text-slate-400">
                    Нет данных — загрузите Risk Report / Trade Report или измените фильтр
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          </div>
        </div>
      )}
    </div>
  )
}
