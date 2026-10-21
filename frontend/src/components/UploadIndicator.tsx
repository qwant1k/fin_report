import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { AlertCircle, CheckCircle2, Loader2, UploadCloud, X } from 'lucide-react'

import { cn } from '@/lib/cn'
import { bindUploadQueryClient, useUploadProgress, useUploadQueue } from '@/lib/uploadQueue'

/**
 * Floating progress of the background upload queue, visible on every page:
 * the user starts the import of the day's documents and keeps working.
 */
export default function UploadIndicator() {
  const qc = useQueryClient()
  const { pathname } = useLocation()
  const { total, done, failed, active, waiting, duplicates, anomalies } = useUploadProgress()
  const clearDone = useUploadQueue((s) => s.clearDone)
  const [hidden, setHidden] = useState(false)

  useEffect(() => bindUploadQueryClient(qc), [qc])
  // a new batch shows the indicator again
  useEffect(() => { if (active + waiting > 0) setHidden(false) }, [active, waiting])

  if (total === 0 || hidden || pathname.startsWith('/documents')) return null
  const running = active + waiting > 0
  const pct = total ? Math.round(((done + failed) / total) * 100) : 0

  return (
    <div className="fixed bottom-4 right-4 z-40 w-80 rounded-xl border border-slate-200 bg-white p-3 shadow-xl">
      <div className="flex items-start gap-2.5">
        <div className={cn(
          'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
          running ? 'bg-sky-100 text-sky-700' : failed || duplicates ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700',
        )}>
          {running ? <Loader2 className="h-4 w-4 animate-spin" />
            : failed || duplicates ? <AlertCircle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-slate-800">
            {running ? 'Загрузка документов' : duplicates ? 'Нужно решение по дублям' : 'Загрузка завершена'}
          </div>
          <div className="text-xs text-slate-600">
            Готово {done} из {total}
            {failed > 0 && <span className="text-red-600"> · ошибок {failed}</span>}
            {duplicates > 0 && <span className="text-amber-700"> · дублей {duplicates}</span>}
            {anomalies > 0 && <span className="text-amber-700"> · аномалий {anomalies}</span>}
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-emerald-500 transition-[width] duration-500" style={{ width: `${pct}%` }} />
          </div>
          <div className="mt-2 flex items-center gap-3 whitespace-nowrap text-xs">
            <Link to="/documents" className="inline-flex items-center gap-1 font-medium text-emerald-700 hover:underline">
              <UploadCloud className="h-3.5 w-3.5" /> Открыть очередь
            </Link>
            {!running && (
              <button type="button" className="text-slate-500 hover:text-slate-700" onClick={clearDone}>
                Очистить готовые
              </button>
            )}
          </div>
        </div>
        <button type="button" onClick={() => setHidden(true)} className="rounded p-0.5 text-slate-400 hover:bg-slate-100" aria-label="Скрыть">
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
