import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Calendar, FileSpreadsheet, FileText, RefreshCw, TrendingDown, TrendingUp, Wallet } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { DashboardResponse } from '@/lib/types'
import { formatNumber, formatPct, formatDate } from '@/lib/format'
import CDUBlockCard from '@/components/CDUBlockCard'
import KpiCard from '@/components/KpiCard'
import HistoryChart from '@/components/HistoryChart'

export default function DashboardPage() {
  const today = new Date().toISOString().slice(0, 10)
  const [reportDate, setReportDate] = useState(today)
  const qc = useQueryClient()

  const { data, isLoading, refetch } = useQuery<DashboardResponse>({
    queryKey: ['dashboard', reportDate],
    queryFn: async () => (await api.get('/dashboard/summary', { params: { report_date: reportDate } })).data,
  })

  const calc = useMutation({
    mutationFn: async () => (await api.post('/calculate/', { report_date: reportDate, recalculate: true })).data,
    onSuccess: (r) => {
      toast.success(`Расчёт за ${formatDate(reportDate)} завершён за ${r.duration_seconds}с — обработано ЧДУ: ${r.cdus_processed}, нарушений: ${r.breaches_count}`)
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const downloadXlsx = async () => {
    const resp = await api.get('/export/xlsx', { params: { report_date: reportDate }, responseType: 'blob' })
    const url = URL.createObjectURL(new Blob([resp.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = `risk_report_${reportDate.replaceAll('-', '')}.xlsx`
    a.click()
    URL.revokeObjectURL(url)
  }

  const downloadPdf = async () => {
    const resp = await api.get('/export/pdf', { params: { report_date: reportDate }, responseType: 'blob' })
    const url = URL.createObjectURL(new Blob([resp.data], { type: 'application/pdf' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `risk_report_${reportDate.replaceAll('-', '')}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Сводный отчёт Фонда</h1>
          <p className="text-sm text-slate-500">
            Дата отчёта: <strong>{formatDate(reportDate)}</strong> · {data?.blocks.length ?? 0} ЧДУ
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Calendar className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="date"
              value={reportDate}
              onChange={(e) => setReportDate(e.target.value)}
              className="input pl-9 w-44"
            />
          </div>
          <button onClick={() => refetch()} className="btn-secondary">
            <RefreshCw className="w-4 h-4" /> Обновить
          </button>
          <button onClick={() => calc.mutate()} disabled={calc.isPending} className="btn-primary">
            <RefreshCw className={`w-4 h-4 ${calc.isPending ? 'animate-spin' : ''}`} /> Пересчитать
          </button>
          <button onClick={downloadXlsx} className="btn-secondary">
            <FileSpreadsheet className="w-4 h-4" /> XLSX
          </button>
          <button onClick={downloadPdf} className="btn-secondary">
            <FileText className="w-4 h-4" /> PDF
          </button>
        </div>
      </header>

      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          title="Активы Фонда"
          value={formatNumber(data?.fund_total_mv ?? 0, 0) + ' ₸'}
          icon={Wallet}
        />
        <KpiCard
          title="Изменение за день"
          value={formatNumber(data?.fund_daily_change ?? 0, 0) + ' ₸'}
          delta={(data?.fund_daily_change ?? 0) >= 0 ? 'up' : 'down'}
          subtitle={formatPct(data?.fund_daily_change_pct ?? 0)}
          icon={(data?.fund_daily_change ?? 0) >= 0 ? TrendingUp : TrendingDown}
        />
        <KpiCard
          title="YTM (взвеш.)"
          value={formatPct(data?.fund_ytm_weighted ?? 0)}
          subtitle={data?.benchmark_ytm != null ? `MBM: ${formatPct(data.benchmark_ytm)}` : 'MBM: —'}
        />
        <KpiCard
          title="Duration (взвеш.)"
          value={formatNumber(data?.fund_duration_weighted ?? 0, 2)}
          subtitle={data?.benchmark_duration != null ? `MBM: ${formatNumber(data.benchmark_duration, 2)}` : 'MBM: —'}
        />
      </section>

      {data && data.breaches_count > 0 && (
        <div className="card p-4 border-l-4 border-red-500 bg-red-50/60">
          <div className="font-semibold text-red-700">⚠️ Нарушений лимитов: {data.breaches_count}</div>
          <div className="text-sm text-red-700/80">См. вкладку «Алерты»</div>
        </div>
      )}

      <section className="card p-4">
        <h2 className="font-semibold mb-3">Динамика портфеля (90 дней)</h2>
        <HistoryChart />
      </section>

      <section className="space-y-6">
        {isLoading && <div className="card p-8 text-center text-slate-500">Загрузка…</div>}
        {!isLoading && data?.blocks.length === 0 && (
          <div className="card p-8 text-center text-slate-500">
            Нет данных за выбранную дату. Загрузите файлы и нажмите «Пересчитать».
          </div>
        )}
        {data?.blocks.map((block) => (
          <CDUBlockCard key={block.cdu_id} block={block} />
        ))}
      </section>
    </div>
  )
}
