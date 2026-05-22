import { useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Activity,
  AlertCircle,
  BookMarked,
  CheckCircle,
  ChevronDown,
  Database,
  FileText,
  FileUp,
  FunctionSquare,
  History,
  LayoutDashboard,
  LineChart,
  LogOut,
  Pencil,
  Settings,
  ShieldAlert,
  Table2,
  TrendingUp,
  Upload,
  Users,
} from 'lucide-react'
import clsx from 'clsx'

import { useAuthStore } from '@/lib/auth'

interface NavItem {
  to: string
  label: string
  icon: typeof LayoutDashboard
  permission: string
  end?: boolean
}

interface NavGroup {
  id: string
  label: string
  icon: typeof LayoutDashboard
  items: NavItem[]
}

const navGroups: NavGroup[] = [
  {
    id: 'dashboard',
    label: 'Дашборд',
    icon: LayoutDashboard,
    items: [
      { to: '/', label: 'Сводка', icon: LayoutDashboard, permission: 'page.dashboard', end: true },
      { to: '/analytics', label: 'Аналитика', icon: LineChart, permission: 'page.analytics' },
      { to: '/alerts', label: 'Алерты', icon: AlertCircle, permission: 'page.alerts' },
    ],
  },
  {
    id: 'upload',
    label: 'Загрузка',
    icon: Upload,
    items: [
      { to: '/upload', label: 'Загрузка XLSX', icon: Upload, permission: 'page.upload' },
      { to: '/primary-data', label: 'Первичка', icon: FileUp, permission: 'page.primary_data' },
      { to: '/reconciliation', label: 'Сверка', icon: CheckCircle, permission: 'page.reconciliation' },
      { to: '/history', label: 'История', icon: History, permission: 'page.history' },
      { to: '/import', label: 'Импорт истории', icon: Database, permission: 'page.import' },
    ],
  },
  {
    id: 'reports',
    label: 'Отчеты',
    icon: FileText,
    items: [
      { to: '/reports', label: 'Сводные отчеты', icon: FileText, permission: 'page.reports' },
      { to: '/positions', label: 'Позиции', icon: Table2, permission: 'page.positions' },
      { to: '/securities', label: 'Справочник ЦБ', icon: BookMarked, permission: 'page.securities' },
      { to: '/risk-report', label: 'Risk Report', icon: ShieldAlert, permission: 'page.risk_report' },
      { to: '/kase', label: 'KASE', icon: TrendingUp, permission: 'page.kase' },
      { to: '/mbm', label: 'MBM', icon: Activity, permission: 'page.mbm' },
    ],
  },
  {
    id: 'settings',
    label: 'Настройки',
    icon: Settings,
    items: [
      { to: '/settings', label: 'ЧДУ и лимиты', icon: Settings, permission: 'page.settings' },
      { to: '/data-editor', label: 'Редактор БД', icon: Pencil, permission: 'page.data_editor' },
      { to: '/formulas', label: 'Формулы', icon: FunctionSquare, permission: 'page.formulas' },
      { to: '/admin', label: 'Пользователи', icon: Users, permission: 'page.admin' },
    ],
  },
]

const ROLE_BADGE: Record<string, string> = {
  admin: 'Администратор',
  analyst: 'Аналитик',
  operator: 'Оператор',
  auditor: 'Аудитор',
  viewer: 'Аудитор',
}

interface NavGroupBlockProps {
  group: NavGroup
  items: NavItem[]
  initiallyOpen: boolean
}

function NavGroupBlock({ group, items, initiallyOpen }: NavGroupBlockProps) {
  const [open, setOpen] = useState(initiallyOpen)

  useEffect(() => {
    if (initiallyOpen) setOpen(true)
  }, [initiallyOpen])

  const Icon = group.icon
  return (
    <div className="mb-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={clsx(
          'flex w-full items-center justify-between rounded-lg px-3 py-2 text-sm font-semibold transition',
          'text-slate-100 hover:bg-white/10',
          initiallyOpen && 'text-emerald-200',
        )}
      >
        <span className="flex items-center gap-3">
          <Icon className="h-4 w-4" />
          {group.label}
        </span>
        <ChevronDown
          className={clsx(
            'h-4 w-4 shrink-0 transition-transform duration-200',
            open ? 'rotate-0' : '-rotate-90',
          )}
        />
      </button>
      <div
        className={clsx(
          'grid overflow-hidden transition-[grid-template-rows] duration-200',
          open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]',
        )}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="ml-3 mt-1 space-y-0.5 border-l border-white/10 pl-3">
            {items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition',
                    isActive
                      ? 'bg-emerald-400 text-emerald-950 shadow-sm shadow-emerald-950/20'
                      : 'text-slate-300 hover:bg-white/10 hover:text-white',
                  )
                }
              >
                <item.icon className="h-3.5 w-3.5" />
                {item.label}
              </NavLink>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function Layout() {
  const role = useAuthStore((s) => s.role)
  const fullName = useAuthStore((s) => s.fullName)
  const permissions = useAuthStore((s) => s.permissions)
  const clear = useAuthStore((s) => s.clear)
  const nav = useNavigate()
  const { pathname } = useLocation()

  const handleLogout = () => {
    clear()
    nav('/login', { replace: true })
  }

  const groupsForRole = useMemo(() => {
    const current = new Set(permissions)
    return navGroups
      .map((group) => ({ group, items: group.items.filter((item) => current.has(item.permission)) }))
      .filter((group) => group.items.length > 0)
  }, [permissions])

  const isGroupActive = (items: NavItem[]) =>
    items.some((it) => (it.end ? pathname === it.to : pathname.startsWith(it.to)))

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

        <nav className="flex-1 overflow-y-auto p-3">
          {groupsForRole.map(({ group, items }) => (
            <NavGroupBlock
              key={group.id}
              group={group}
              items={items}
              initiallyOpen={isGroupActive(items)}
            />
          ))}
        </nav>

        <div className="border-t border-white/10 p-3">
          <div className="text-sm font-semibold">{fullName ?? 'Пользователь'}</div>
          <div className="mb-3 text-xs text-emerald-100/70">
            {role ? (ROLE_BADGE[role] ?? role) : '-'}
          </div>
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
