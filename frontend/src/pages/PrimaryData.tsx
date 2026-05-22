import { useState, useCallback, useEffect, ReactNode } from 'react'
import { FileUp, CheckCircle, AlertTriangle, Clock, FileSpreadsheet, FileText, Building2, Trash2, RefreshCw } from 'lucide-react'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

interface SourceDoc {
  id: number
  filename: string
  file_type: string
  file_size: number
  import_status: string
  imported_at: string
  imported_by: string | null
  source_cdu: string | null
}

const FILE_TYPE_LABELS: Record<string, string> = {
  trade_report: 'Trade Report',
  holdings: 'Holdings',
  reconciliation: 'Сверка',
  exchange_certificate: 'Биржевое свидетельство',
  pdf_statement: 'Выписка PDF',
  unknown: 'Неизвестно',
}

const FILE_TYPE_ICONS: Record<string, ReactNode> = {
  trade_report: <FileSpreadsheet className="w-4 h-4 text-emerald-600" />,
  holdings: <FileSpreadsheet className="w-4 h-4 text-blue-600" />,
  reconciliation: <FileText className="w-4 h-4 text-amber-600" />,
  exchange_certificate: <FileText className="w-4 h-4 text-purple-600" />,
  pdf_statement: <FileText className="w-4 h-4 text-red-600" />,
}

export default function PrimaryDataPage() {
  const [file, setFile] = useState<File | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [docs, setDocs] = useState<SourceDoc[]>([])
  const [docsLoading, setDocsLoading] = useState(false)
  const canUpload = useAuthStore((s) => s.can('primary_data.upload'))

  const fetchDocs = async () => {
    setDocsLoading(true)
    try {
      const res = await api.get('/primary-data/documents?limit=50')
      setDocs(res.data)
    } catch {
      // silent
    } finally {
      setDocsLoading(false)
    }
  }

  useEffect(() => {
    fetchDocs()
  }, [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0])
  }, [])

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(true)
  }

  const onDragLeave = () => setDragOver(false)

  const handleUpload = async () => {
    if (!file) return
    setLoading(true)
    setError(null)
    setResult(null)
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await api.post('/primary-data/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setResult(res.data)
      fetchDocs()
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Ошибка загрузки')
    } finally {
      setLoading(false)
      setFile(null)
    }
  }

  const statusColor = (s: string) => {
    if (s === 'completed') return 'text-emerald-600 bg-emerald-50 border-emerald-200'
    if (s === 'error') return 'text-red-600 bg-red-50 border-red-200'
    if (s === 'skipped') return 'text-slate-600 bg-slate-50 border-slate-200'
    return 'text-amber-600 bg-amber-50 border-amber-200'
  }

  const formatDate = (d: string) => {
    if (!d) return '-'
    const dt = new Date(d)
    return dt.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
  }

  const formatSize = (n: number) => {
    if (n < 1024) return `${n} B`
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
    return `${(n / (1024 * 1024)).toFixed(1)} MB`
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-800">Первичные данные</h1>
        <button onClick={fetchDocs} disabled={docsLoading} className="btn btn-secondary text-sm">
          <RefreshCw className={`w-4 h-4 ${docsLoading ? 'animate-spin' : ''}`} />
          Обновить
        </button>
      </div>

      {/* Upload zone */}
      {canUpload && (
      <div className="bg-white rounded-xl border border-slate-200 p-6 space-y-4">
        <h2 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
          <FileUp className="w-4 h-4 text-emerald-600" />
          Загрузка файла
        </h2>

        <div
          onDrop={onDrop}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          className={`border-2 border-dashed rounded-xl p-8 text-center transition cursor-pointer relative ${
            dragOver ? 'border-emerald-500 bg-emerald-50' : 'border-slate-300 hover:border-slate-400 bg-slate-50'
          }`}
        >
          <FileUp className="w-10 h-10 mx-auto text-slate-400 mb-3" />
          <p className="text-sm text-slate-600">
            Перетащите файл сюда или <span className="text-emerald-700 font-medium">нажмите для выбора</span>
          </p>
          <p className="text-xs text-slate-400 mt-1">
            Trade Report XLSX, Holdings, Сверка, Биржевые свидетельства (PDF/PNG/DOCX), Выписки PDF
          </p>
          <input
            type="file"
            className="hidden"
            id="primary-file"
            onChange={(e) => e.target.files?.[0] && setFile(e.target.files[0])}
          />
          <label htmlFor="primary-file" className="absolute inset-0 cursor-pointer" />
        </div>

        {file && (
          <div className="flex items-center justify-between bg-slate-50 rounded-lg p-3 border border-slate-200">
            <div className="flex items-center gap-3">
              <FileSpreadsheet className="w-5 h-5 text-emerald-600" />
              <div>
                <div className="text-sm font-medium text-slate-800">{file.name}</div>
                <div className="text-xs text-slate-500">{formatSize(file.size)}</div>
              </div>
            </div>
            <button onClick={handleUpload} disabled={loading} className="btn btn-primary">
              {loading ? 'Импорт…' : 'Импортировать'}
            </button>
          </div>
        )}

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-red-800 text-sm">
            <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
            {error}
          </div>
        )}

        {result && (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 space-y-1">
            <div className="flex items-center gap-2 text-emerald-700 font-semibold text-sm">
              <CheckCircle className="w-4 h-4" />
              {result.status === 'skipped' ? 'Пропущено (дубликат)' : 'Импорт завершён'}
            </div>
            <div className="text-xs text-slate-600">{result.message}</div>
          </div>
        )}
      </div>
      )}

      {/* Recent documents table */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
            <Clock className="w-4 h-4 text-slate-500" />
            История загрузок
          </h2>
          <span className="text-xs text-slate-400">{docs.length} документов</span>
        </div>

        {docs.length === 0 && !docsLoading && (
          <div className="px-6 py-8 text-center text-slate-400 text-sm">
            Нет загруженных документов
          </div>
        )}

        {docs.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-2 text-left text-slate-600 font-medium">Файл</th>
                <th className="px-4 py-2 text-left text-slate-600 font-medium">Тип</th>
                <th className="px-4 py-2 text-left text-slate-600 font-medium">Статус</th>
                <th className="px-4 py-2 text-left text-slate-600 font-medium">ЧДУ</th>
                <th className="px-4 py-2 text-right text-slate-600 font-medium">Размер</th>
                <th className="px-4 py-2 text-left text-slate-600 font-medium">Загружен</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id} className="border-t hover:bg-slate-50">
                  <td className="px-4 py-2 text-slate-800 font-medium truncate max-w-[200px]" title={d.filename}>
                    {d.filename}
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-1.5 text-xs text-slate-600">
                      {FILE_TYPE_ICONS[d.file_type] || <FileText className="w-4 h-4 text-slate-400" />}
                      {FILE_TYPE_LABELS[d.file_type] || d.file_type}
                    </div>
                  </td>
                  <td className="px-4 py-2">
                    <span className={`text-xs px-2 py-0.5 rounded border ${statusColor(d.import_status)}`}>
                      {d.import_status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-slate-600">
                    {d.source_cdu ? (
                      <span className="flex items-center gap-1 text-xs">
                        <Building2 className="w-3 h-3" />
                        {d.source_cdu}
                      </span>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right text-slate-600 text-xs">{formatSize(d.file_size)}</td>
                  <td className="px-4 py-2 text-slate-600 text-xs">{formatDate(d.imported_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
