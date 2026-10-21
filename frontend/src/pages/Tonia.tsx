import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, ExternalLink, Percent, RefreshCw, Upload } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { apiErrorMessage, notificationText } from '@/lib/notifications'
import { useAuthStore } from '@/lib/auth'
import { formatDate, formatNumber } from '@/lib/format'
import { PageHeader } from '@/components/ui'
import Modal from '@/components/ui/Modal'
import { IssueEditor, type ReferenceIssue } from '@/components/ReferenceBook'

interface Row { date: string; TCI?: number; TCR_1M?: number; TCR_3M?: number; TCR_6M?: number; updated_at: string | null; updated_by: string | null }
interface FloatIssue { isin: string; ticker: string | null; index: string | null; margin_pct: number | null; coupon_text: string | null }
interface Data {
  rows: Row[]
  total_dates: number
  kase_page: string
  float_issues: FloatIssue[]
  auto_fetch: { enabled: boolean; time: string; timezone: string }
}

/** «Рынок → TONIA Compounded»: загрузка файла KASE и хранимые значения TCI / TCR. */
export default function ToniaPage() {
  const qc = useQueryClient()
  const can = useAuthStore((s) => s.can)
  const input = useRef<HTMLInputElement>(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [selectedIssue, setSelectedIssue] = useState<FloatIssue | null>(null)
  const q = useQuery<Data>({
    queryKey: ['tonia', from, to],
    queryFn: async () => (await api.get('/tonia/', { params: { from: from || undefined, to: to || undefined } })).data,
  })
  const upload = useMutation({
    mutationFn: async (files: FileList) => {
      const out = []
      for (const f of Array.from(files)) {
        const fd = new FormData()
        fd.append('file', f)
        out.push((await api.post('/tonia/upload', fd)).data)
      }
      return out
    },
    onSuccess: (res) => {
      for (const r of res) {
        toast.success(notificationText(r.message, 'Файл TONIA Compounded обработан'), { duration: 7000 })
        for (const w of r.warnings ?? []) toast(notificationText(w, 'При загрузке TONIA обнаружено предупреждение'), { icon: '⚠️' })
      }
      qc.invalidateQueries({ queryKey: ['tonia'] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось загрузить файл TONIA Compounded')),
    onSettled: () => { if (input.current) input.current.value = '' },
  })
  const refresh = useMutation({
    mutationFn: async () => (await api.post('/tonia/refresh')).data,
    onSuccess: (res) => {
      toast.success(notificationText(res.message, 'Данные TONIA Compounded обновлены с KASE'), { duration: 7000 })
      for (const w of res.warnings ?? []) toast(notificationText(w, 'При обновлении TONIA обнаружено предупреждение'), { icon: '⚠️' })
      qc.invalidateQueries({ queryKey: ['tonia'] })
    },
    onError: (error: unknown) => toast.error(apiErrorMessage(error, 'Не удалось автоматически обновить TONIA Compounded с KASE')),
  })
  const issueQ = useQuery<ReferenceIssue | null>({
    queryKey: ['tonia-reference', selectedIssue?.isin],
    enabled: Boolean(selectedIssue?.isin),
    queryFn: async () => {
      const rows: ReferenceIssue[] = (await api.get('/securities/reference', {
        params: { search: selectedIssue!.isin, limit: 20 },
      })).data
      const key = selectedIssue!.isin.toUpperCase()
      return rows.find((row) => row.isin.toUpperCase() === key || row.ticker_kase?.toUpperCase() === key) ?? null
    },
  })

  const d = q.data
  return (
    <div className="space-y-5">
      <PageHeader
        title="TONIA Compounded"
        icon={Percent}
        subtitle="Индикаторы KASE TCI и TCR_1M / TCR_3M / TCR_6M — для купонов облигаций с плавающей ставкой"
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            {d?.kase_page && (
              <a href={d.kase_page} target="_blank" rel="noreferrer" className="btn-secondary h-9">
                <ExternalLink className="h-4 w-4" /> Страница KASE
              </a>
            )}
            {can('kase.refresh') && (
              <>
                <button type="button" className="btn-primary h-9" disabled={refresh.isPending}
                  onClick={() => refresh.mutate()}>
                  <RefreshCw className={`h-4 w-4 ${refresh.isPending ? 'animate-spin' : ''}`} />
                  {refresh.isPending ? 'Обновление…' : 'Обновить с KASE'}
                </button>
                <input ref={input} type="file" accept=".xlsx,.xls" multiple className="hidden"
                  onChange={(e) => e.target.files?.length && upload.mutate(e.target.files)} />
                <button type="button" className="btn-secondary h-9" disabled={upload.isPending} onClick={() => input.current?.click()}>
                  <Upload className="h-4 w-4" /> {upload.isPending ? 'Загрузка…' : 'Загрузить файл KASE'}
                </button>
              </>
            )}
          </div>
        )}
      />

      <div className="card space-y-2 p-4 text-sm text-slate-600">
        <p>Данные автоматически загружаются из официального архива KASE каждый день
          {d?.auto_fetch?.enabled ? ` в ${d.auto_fetch.time} (${d.auto_fetch.timezone})` : ''}. Кнопка «Обновить с KASE»
          запускает загрузку немедленно. Загрузка Excel-файла остаётся доступна как резервный способ; повторный импорт
          обновляет значения и не создаёт дублей.</p>
        <p>Купон облигации с плавающей ставкой = индикатор выпуска (TCR) на дату начала купонного периода + маржа выпуска.
          Если на эту дату значения нет, берётся последнее опубликованное до неё. Индикатор и маржа задаются в
          «Справочник ЦБ → Выпуски и графики купонов»; сдвиг даты фиксации — в «Формулы → Параметры расчёта».</p>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_380px]">
        <div className="card overflow-hidden">
          <div className="flex flex-wrap items-end gap-3 border-b border-slate-100 px-4 py-3">
            <div className="mr-auto text-sm font-semibold text-slate-800">Значения ({d?.total_dates ?? 0} дат)</div>
            <label><span className="field-label">с</span><input type="date" className="input-sm" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
            <label><span className="field-label">по</span><input type="date" className="input-sm" value={to} onChange={(e) => setTo(e.target.value)} /></label>
          </div>
          <div className="table-wrap">
            <table className="detail-table w-full">
              <thead>
                <tr><th>Дата расчёта</th><th className="num">TCI</th><th className="num">TCR_1M, %</th><th className="num">TCR_3M, %</th><th className="num">TCR_6M, %</th><th>Загружено</th></tr>
              </thead>
              <tbody>
                {(d?.rows ?? []).map((r) => (
                  <tr key={r.date}>
                    <td>{formatDate(r.date)}</td>
                    <td className="num">{r.TCI != null ? formatNumber(r.TCI, 10) : '—'}</td>
                    <td className="num">{r.TCR_1M != null ? formatNumber(r.TCR_1M, 4) : '—'}</td>
                    <td className="num">{r.TCR_3M != null ? formatNumber(r.TCR_3M, 4) : '—'}</td>
                    <td className="num">{r.TCR_6M != null ? formatNumber(r.TCR_6M, 4) : '—'}</td>
                    <td className="text-xs text-slate-500">{r.updated_at ? new Date(r.updated_at).toLocaleString('ru-RU') : '—'}{r.updated_by ? ` · ${r.updated_by}` : ''}</td>
                  </tr>
                ))}
                {!q.isLoading && !d?.rows.length && <tr><td colSpan={6} className="py-8 text-center text-slate-400">Данных нет — загрузите файл KASE</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
        <div className="card h-max p-4">
          <div className="mb-2 text-sm font-semibold text-slate-800">Выпуски с плавающей ставкой</div>
          {!!d?.float_issues.length && <div className="mb-2 text-xs text-slate-500">Нажмите на выпуск, чтобы открыть карточку и задать индикатор.</div>}
          {!d?.float_issues.length && <div className="text-sm text-slate-500">В справочнике нет выпусков с плавающим купоном</div>}
          <div className="space-y-1.5">
            {(d?.float_issues ?? []).map((i) => (
              <button key={i.isin} type="button" onClick={() => setSelectedIssue(i)}
                className="group flex w-full items-center gap-2 rounded-lg border border-slate-200 px-2.5 py-1.5 text-left text-xs transition hover:border-emerald-300 hover:bg-emerald-50 focus:outline-none focus:ring-2 focus:ring-emerald-500/30"
                aria-label={`Открыть карточку выпуска ${i.ticker ?? i.isin}`}>
                <div className="min-w-0 flex-1"><div className="truncate font-mono font-semibold">{i.ticker ?? i.isin}</div><div className="truncate text-slate-500">{i.isin}</div></div>
                <div className="shrink-0 text-right">
                  {i.index
                    ? <span className="font-semibold text-emerald-800">{i.index}{i.margin_pct != null ? ` + ${formatNumber(i.margin_pct, 2)}%` : ''}</span>
                    : <span className="text-amber-700" title={i.coupon_text ?? ''}>индикатор не задан</span>}
                </div>
                <ChevronRight className="h-4 w-4 shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-emerald-600" />
              </button>
            ))}
          </div>
        </div>
      </div>

      <Modal open={Boolean(selectedIssue)} onClose={() => setSelectedIssue(null)} size="xl">
        {issueQ.isLoading && <div className="py-12 text-center text-sm text-slate-500">Загрузка карточки выпуска…</div>}
        {!issueQ.isLoading && issueQ.data && (
          <IssueEditor
            key={issueQ.data.isin}
            issue={issueQ.data}
            isNew={false}
            canWrite={can('securities.edit')}
            onClose={() => setSelectedIssue(null)}
            onSaved={(saved) => {
              qc.setQueryData(['tonia-reference', selectedIssue?.isin], saved)
              qc.invalidateQueries({ queryKey: ['tonia'] })
              qc.invalidateQueries({ queryKey: ['reference-book'] })
            }}
          />
        )}
        {!issueQ.isLoading && !issueQ.data && (
          <div className="py-12 text-center text-sm text-rose-700">Карточка выпуска не найдена в справочнике ЦБ.</div>
        )}
      </Modal>
    </div>
  )
}
