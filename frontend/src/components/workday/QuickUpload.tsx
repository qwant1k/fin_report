import { useDropzone } from 'react-dropzone'
import { Link } from 'react-router-dom'
import { Loader2, UploadCloud } from 'lucide-react'
import toast from 'react-hot-toast'

import { cn } from '@/lib/cn'
import { makeQueueItems, useUploadProgress, useUploadQueue } from '@/lib/uploadQueue'

/**
 * Compact drop zone right inside the «Загрузка» step of the work day:
 * files go to the global background queue and start immediately, so the user
 * can move on to the next steps while the rest of the documents are imported.
 */
export default function QuickUpload({ workDate, disabled }: { workDate: string; disabled?: boolean }) {
  const add = useUploadQueue((s) => s.add)
  const { total, done, failed, active, waiting } = useUploadProgress()
  const running = active + waiting > 0

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    multiple: true,
    disabled,
    onDrop: (files) => {
      if (!files.length) return
      add(makeQueueItems(files, workDate), true)
      toast(`Начата загрузка файлов: ${files.length}. Можно продолжать работу; прогресс отображается в верхней панели.`, { icon: '⏳' })
    },
  })

  return (
    <div className="mt-3 space-y-2">
      <div
        {...getRootProps()}
        className={cn(
          'flex cursor-pointer items-center gap-3 rounded-xl border-2 border-dashed px-4 py-3 text-sm transition',
          isDragActive ? 'border-emerald-500 bg-emerald-50' : 'border-slate-300 bg-white hover:border-emerald-400',
          disabled && 'cursor-not-allowed opacity-60',
        )}
      >
        <input {...getInputProps()} />
        <UploadCloud className="h-5 w-5 shrink-0 text-emerald-600" />
        <span className="text-slate-700">
          Перетащите документы сюда или нажмите — загрузка начнётся сразу, в фоне.
          <span className="block text-xs text-slate-500">
            Не нужно ждать все файлы: каждый ЧДУ можно считать и сверять, как только загружен его документ.
          </span>
        </span>
      </div>
      {total > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
          {running && <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-600" />}
          <span>
            {running ? 'Идёт загрузка' : 'Загрузка завершена'}: готово {done} из {total}
            {failed > 0 && <span className="text-red-600">, ошибок {failed}</span>}
          </span>
          <Link to="/documents" className="font-medium text-emerald-700 hover:underline">Подробнее</Link>
        </div>
      )}
    </div>
  )
}
