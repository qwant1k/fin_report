import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Upload,
  History,
  TrendingUp,
  Activity,
  AlertCircle,
  Settings,
  Users,
  FunctionSquare,
  Database,
  LineChart,
  LogOut,
  FileUp,
  CheckCircle,
  Table2,
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
    <div className="flex min-h-screen">
      <aside className="w-60 bg-kdif-green text-white flex flex-col">
        <div className="p-6 border-b border-emerald-700/40">
          <div className="text-lg font-bold leading-tight">КФГД</div>
          <div className="text-xs text-emerald-100/80 mt-0.5">Fund Reporting</div>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition',
                  isActive
                    ? 'bg-white/15 text-white font-semibold'
                    : 'text-emerald-50 hover:bg-white/10',
                )
              }
            >
              <item.icon className="w-4 h-4" />
              {item.label}
            </NavLink>
          ))}
          {isAdmin && (
            <>
              <div className="text-[10px] uppercase tracking-wider text-emerald-200/70 mt-4 mb-1 px-3">
                Admin
              </div>
              {adminItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    clsx(
                      'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition',
                      isActive
                        ? 'bg-white/15 text-white font-semibold'
                        : 'text-emerald-50 hover:bg-white/10',
                    )
                  }
                >
                  <item.icon className="w-4 h-4" />
                  {item.label}
                </NavLink>
              ))}
            </>
          )}
        </nav>
        <div className="p-3 border-t border-emerald-700/40">
          <div className="text-sm font-medium">{fullName ?? 'Пользователь'}</div>
          <div className="text-xs text-emerald-100/70 mb-3">{role}</div>
          <button onClick={handleLogout} className="btn w-full bg-white/10 hover:bg-white/20 text-white">
            <LogOut className="w-4 h-4" /> Выйти
          </button>
        </div>
      </aside>

      <main className="flex-1 p-8 overflow-x-auto">
        <Outlet />
      </main>
    </div>
  )
}
