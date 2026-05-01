import { useCallback, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileSpreadsheet, Trash2, UploadCloud, AlertCircle, CheckCircle2 } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { TradeFile, CDU } from '@/lib/types'
import { formatDate } from '@/lib/format'

export default function UploadPage() {
  const qc = useQueryClient()
  const [pendingCdu, setPendingCdu] = useState<number | ''>('')
  const [pendingDate, setPendingDate] = useState<string>('')

  const cdus = useQuery<CDU[]>({
    queryKey: ['cdus'],
    queryFn: async () => (await api.get('/settings/cdus')).data,
  })

  const files = useQuery<TradeFile[]>({
    queryKey: ['trade-files'],
    queryFn: async () => (await api.get('/upload/files')).data,
  })

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      if (pendingCdu) fd.append('cdu_id', String(pendingCdu))
      if (pendingDate) fd.append('trade_date', pendingDate)
      return (await api.post('/upload/trade-report', fd, { headers: { 'Content-Type': 'multipart/form-data' } })).data
    },
    onSuccess: (r) => {
      toast.success(`${r.cdu_name ?? 'Файл'} • строк: ${r.rows_parsed}, пропущено: ${r.rows_skipped}`)
      qc.invalidateQueries({ queryKey: ['trade-files'] })
    },
  })

  const onDrop = useCallback((accepted: File[]) => {
    accepted.forEach((f) => upload.mutate(f))
  }, [upload])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel.sheet.macroEnabled.12': ['.xlsm'],
    },
    multiple: true,
  })

  const setCdu = useMutation({
    mutationFn: async ({ id, cduId }: { id: number; cduId: number }) =>
      (await api.put(`/upload/files/${id}/cdu`, null, { params: { cdu_id: cduId } })).data,
    onSuccess: () => {
      toast.success('ЧДУ обновлён')
      qc.invalidateQueries({ queryKey: ['trade-files'] })
    },
  })

  const remove = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/upload/files/${id}`)).data,
    onSuccess: () => {
      toast.success('Файл удалён')
      qc.invalidateQueries({ queryKey: ['trade-files'] })
    },
  })

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Загрузка отчётов от ЧДУ</h1>
        <p className="text-sm text-slate-500">XLSX выгрузка KASE-сделок (TradeReport)</p>
      </header>

      <div className="card p-4 space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="label">ЧДУ (опционально, иначе авто)</label>
            <select className="input" value={pendingCdu} onChange={(e) => setPendingCdu(e.target.value ? Number(e.target.value) : '')}>
              <option value="">Авто-определение</option>
              {cdus.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Дата торгов (опционально)</label>
            <input type="date" className="input" value={pendingDate} onChange={(e) => setPendingDate(e.target.value)} />
          </div>
        </div>
        <div
          {...getRootProps()}
          className={`border-2 border-dashed rounded-lg p-10 text-center cursor-pointer transition ${
            isDragActive ? 'border-kdif-green bg-emerald-50' : 'border-slate-300 hover:border-kdif-green'
          }`}
        >
          <input {...getInputProps()} />
          <UploadCloud className="w-10 h-10 mx-auto mb-2 text-slate-400" />
          <div className="font-medium">Перетащите XLSX/XLSM сюда или кликните для выбора</div>
          <div className="text-xs text-slate-500 mt-1">Можно загружать несколько файлов одновременно</div>
        </div>
      </div>

      <div className="card overflow-hidden">
        <div className="p-4 border-b border-slate-100 font-semibold">История загрузок</div>
        <div className="table-wrap">
          <table className="kdif-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Файл</th>
                <th>ЧДУ</th>
                <th>Дата торгов</th>
                <th>Загружено</th>
                <th>Парсинг</th>
                <th>Статус</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(files.data ?? []).map((f) => (
                <tr key={f.id}>
                  <td>{f.id}</td>
                  <td className="flex items-center gap-2">
                    <FileSpreadsheet className="w-4 h-4 text-emerald-600" /> {f.filename}
                  </td>
                  <td>
                    <select
                      className="input py-1"
                      defaultValue={f.cdu_id ?? ''}
                      onChange={(e) => setCdu.mutate({ id: f.id, cduId: Number(e.target.value) })}
                    >
                      <option value="">— выбрать —</option>
                      {cdus.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                  </td>
                  <td>{formatDate(f.trade_date)}</td>
                  <td>{formatDate(f.uploaded_at)}</td>
                  <td>{f.rows_parsed} / {f.rows_skipped}</td>
                  <td>
                    {f.status === 'PARSED'
                      ? <span className="badge-ok"><CheckCircle2 className="w-3 h-3 inline mr-1" />{f.status}</span>
                      : <span className="badge-warn"><AlertCircle className="w-3 h-3 inline mr-1" />{f.status}</span>}
                  </td>
                  <td>
                    <button onClick={() => remove.mutate(f.id)} className="btn-secondary text-red-600 px-2 py-1">
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
              {!files.data?.length && (
                <tr>
                  <td colSpan={8} className="text-center text-slate-400 py-6">Файлов пока нет</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
