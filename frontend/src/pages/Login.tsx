import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Lock, User } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

export default function LoginPage() {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('admin')
  const [loading, setLoading] = useState(false)
  const setSession = useAuthStore((s) => s.setSession)
  const nav = useNavigate()

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      const { data } = await api.post('/auth/login', { username, password })
      setSession(data.access_token, data.role, data.full_name ?? null)
      toast.success(`Добро пожаловать${data.full_name ? `, ${data.full_name}` : ''}!`)
      nav('/', { replace: true })
    } catch {
      // toast handled in interceptor
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-emerald-700 via-emerald-600 to-emerald-800 p-6">
      <div className="card w-full max-w-md p-8">
        <div className="text-center mb-6">
          <div className="text-2xl font-bold text-kdif-green">КФГД</div>
          <div className="text-sm text-slate-500">Fund Reporting · вход</div>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="label">Логин</label>
            <div className="relative">
              <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                className="input pl-9"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
              />
            </div>
          </div>
          <div>
            <label className="label">Пароль</label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="password"
                className="input pl-9"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </div>
          <button type="submit" disabled={loading} className="btn-primary w-full">
            {loading ? 'Входим…' : 'Войти'}
          </button>
        </form>
        <p className="text-xs text-slate-400 text-center mt-6">
          По умолчанию admin/admin — поменяйте после первого входа.
        </p>
      </div>
    </div>
  )
}
