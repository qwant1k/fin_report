import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  BarChart3,
  Eye,
  EyeOff,
  Lock,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  User,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { Spinner } from '@/components/ui'
import { apiErrorMessage } from '@/lib/notifications'

const HIGHLIGHTS = [
  { icon: TrendingUp, title: 'Аналитика портфеля', text: 'Динамика, доходность и дюрация в реальном времени' },
  { icon: ShieldCheck, title: 'Контроль лимитов', text: 'Автоматические алерты по нарушениям и сверка с KASE' },
  { icon: BarChart3, title: 'Сводная отчётность', text: 'Отчёты Фонда с утверждением и экспортом в XLSX/PDF' },
]

export default function LoginPage() {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('admin')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const setSession = useAuthStore((s) => s.setSession)
  const nav = useNavigate()

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      const { data } = await api.post('/auth/login', { username, password })
      setSession(data.access_token, data.role, data.full_name ?? null, data.permissions ?? [])
      toast.success(`Добро пожаловать${data.full_name ? `, ${data.full_name}` : ''}!`)
      nav('/', { replace: true })
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Не удалось войти в систему'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      {/* Brand panel */}
      <div className="relative hidden overflow-hidden bg-gradient-to-br from-emerald-800 via-emerald-700 to-teal-800 lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div className="absolute inset-0 bg-grid opacity-[0.07]" />
        <motion.div
          className="pointer-events-none absolute -right-24 top-10 h-72 w-72 rounded-full bg-emerald-400/30 blur-3xl"
          animate={{ y: [0, 24, 0], opacity: [0.5, 0.8, 0.5] }}
          transition={{ duration: 8, repeat: Infinity, ease: 'easeInOut' }}
        />
        <motion.div
          className="pointer-events-none absolute -bottom-20 left-10 h-72 w-72 rounded-full bg-teal-300/20 blur-3xl"
          animate={{ y: [0, -20, 0] }}
          transition={{ duration: 10, repeat: Infinity, ease: 'easeInOut' }}
        />

        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="relative flex items-center gap-3 text-white"
        >
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white/15 text-xl font-black backdrop-blur">
            К
          </div>
          <div>
            <div className="font-display text-xl font-bold">КФГД</div>
            <div className="text-sm text-emerald-100/80">Fund Reporting Platform</div>
          </div>
        </motion.div>

        <div className="relative">
          <motion.h2
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.1 }}
            className="max-w-md font-display text-3xl font-bold leading-snug text-white"
          >
            Управление портфелем Фонда — <span className="text-emerald-200">точно и наглядно</span>
          </motion.h2>
          <div className="mt-8 space-y-4">
            {HIGHLIGHTS.map((h, i) => (
              <motion.div
                key={h.title}
                initial={{ opacity: 0, x: -16 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.5, delay: 0.2 + i * 0.1 }}
                className="flex items-start gap-3 rounded-2xl bg-white/10 p-3.5 backdrop-blur"
              >
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/15 text-white">
                  <h.icon className="h-5 w-5" />
                </div>
                <div>
                  <div className="font-semibold text-white">{h.title}</div>
                  <div className="text-sm text-emerald-100/75">{h.text}</div>
                </div>
              </motion.div>
            ))}
          </div>
        </div>

        <div className="relative text-xs text-emerald-100/60">© {new Date().getFullYear()} КФГД · Fund Reporting</div>
      </div>

      {/* Form panel */}
      <div className="flex items-center justify-center bg-slate-50 p-6">
        <motion.div
          initial={{ opacity: 0, y: 16, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
          className="card w-full max-w-md p-8"
        >
          <div className="mb-7 text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-gradient text-2xl font-black text-white shadow-glow lg:hidden">
              К
            </div>
            <div className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700 ring-1 ring-emerald-600/15">
              <Sparkles className="h-3.5 w-3.5" /> Добро пожаловать
            </div>
            <h1 className="mt-3 text-2xl font-bold text-slate-900">Вход в систему</h1>
            <p className="mt-1 text-sm text-slate-500">Введите учётные данные для продолжения</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="label">Логин</label>
              <div className="relative">
                <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  className="input pl-9"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoFocus
                  autoComplete="username"
                />
              </div>
            </div>
            <div>
              <label className="label">Пароль</label>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  className="input px-9"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-md p-1 text-slate-400 transition hover:text-slate-700"
                  aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            <button type="submit" disabled={loading} className="btn-primary mt-2 w-full">
              {loading ? (
                <>
                  <Spinner /> Входим…
                </>
              ) : (
                'Войти'
              )}
            </button>
          </form>

          <p className="mt-6 rounded-xl bg-slate-100 px-3 py-2 text-center text-xs text-slate-500">
            По умолчанию <span className="font-mono font-semibold text-slate-700">admin / admin</span> — поменяйте после первого входа.
          </p>
        </motion.div>
      </div>
    </div>
  )
}
