import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  Activity,
  AlertCircle,
  CheckCircle,
  Database,
  FileUp,
  FunctionSquare,
  History,
  LayoutDashboard,
  LineChart,
  LogOut,
  Settings,
  Table2,
  TrendingUp,
  Upload,
  Users,
} from 'lucide-react'
import clsx from 'clsx'

import { useAuthStore } from '@/lib/auth'

const navItems = [
  { to: '/', label: 'Дашборд', icon: LayoutDashboard, end: true },
  { to: '/analytics', label: 'Аналитика', icon: LineChart },
  { to: '/primary-data', label: 'Первичка', icon: FileUp },
  { to: '/reconciliation', label: 'Сверка', icon: CheckCircle },
  { to: '/positions', label: 'Позиции', icon: Table2 },
  { to: '/upload', label: 'Загрузка', icon: Upload },
  { to: '/history', label: 'История', icon: History },
  { to: '/kase', label: 'KASE', icon: TrendingUp },
  { to: '/mbm', label: 'MBM', icon: Activity },
  { to: '/alerts', label: 'Алерты', icon: AlertCircle },
  { to: '/settings', label: 'Настройки', icon: Settings },
]

const adminItems = [
  { to: '/import', label: 'Импорт истории', icon: Database },
  { to: '/formulas', label: 'Формулы', icon: FunctionSquare },
  { to: '/admin', label: 'Админ', icon: Users },
]

export default function Layout() {
  const isAdmin = useAuthStore((s) => s.isAdmin())
  const fullName = useAuthStore((s) => s.fullName)
  const role = useAuthStore((s) => s.role)
  const clear = useAuthStore((s) => s.clear)
  const nav = useNavigate()

  const handleLogout = () => {
    clear()
    nav('/login', { replace: true })
  }

  return (
    <div className="flex min-h-screen bg-slate-100">
      <aside className="sticky top-0 flex h-screen w-64 flex-col border-r border-emerald-900/40 bg-slate-950 text-white shadow-2xl shadow-slate-950/20">
        <div className="border-b border-white/10 p-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-400 text-sm font-black text-emerald-950 shadow-sm shadow-emerald-950/20">
              K
            </div>
            <div>
              <div className="text-lg font-bold leading-tight">КФГД</div>
              <div className="mt-0.5 text-xs font-medium text-emerald-100/75">Fund Reporting</div>
            </div>
          </div>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto p-3">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition',
                  isActive
                    ? 'bg-emerald-400 text-emerald-950 shadow-sm shadow-emerald-950/20'
                    : 'text-slate-200 hover:bg-white/10 hover:text-white',
                )
              }
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </NavLink>
          ))}

          {isAdmin && (
            <>
              <div className="mb-1 mt-4 px-3 text-[10px] uppercase tracking-wider text-emerald-200/70">
                Admin
              </div>
              {adminItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    clsx(
                      'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition',
                      isActive
                        ? 'bg-emerald-400 text-emerald-950 shadow-sm shadow-emerald-950/20'
                        : 'text-slate-200 hover:bg-white/10 hover:text-white',
                    )
                  }
                >
                  <item.icon className="h-4 w-4" />
                  {item.label}
                </NavLink>
              ))}
            </>
          )}
        </nav>

        <div className="border-t border-white/10 p-3">
          <div className="text-sm font-semibold">{fullName ?? 'Пользователь'}</div>
          <div className="mb-3 text-xs text-emerald-100/70">{role}</div>
          <button onClick={handleLogout} className="btn w-full border border-white/10 bg-white/10 text-white hover:bg-white/20">
            <LogOut className="h-4 w-4" />
            Выйти
          </button>
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-x-auto p-5 lg:p-8">
        <Outlet />
      </main>
    </div>
  )
}
