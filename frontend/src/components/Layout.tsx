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

import { Role, useAuthStore } from '@/lib/auth'

interface NavItem {
  to: string
  label: string
  icon: typeof LayoutDashboard
  end?: boolean
  roles?: Role[]
}

interface NavGroup {
  id: string
  label: string
  icon: typeof LayoutDashboard
  items: NavItem[]
}

const ALL: Role[] = ['admin', 'analyst', 'operator', 'auditor', 'viewer']
const NON_AUDITOR: Role[] = ['admin', 'analyst', 'operator']

// Operator profile is upload-centric: only the surfaces they actively work
// with show up. Everyone else sees the full read suite; writes are still
// gated server-side by `require_write` / `require_admin`.
const OPERATOR_VISIBLE = new Set([
  '/', '/upload', '/primary-data', '/reconciliation', '/history', '/alerts',
])

const navGroups: NavGroup[] = [
  {
    id: 'dashboard',
    label: 'Дашборд',
    icon: LayoutDashboard,
    items: [
      { to: '/',           label: 'Сводка',     icon: LayoutDashboard, end: true, roles: ALL },
      { to: '/analytics',  label: 'Аналитика',  icon: LineChart,                  roles: ALL },
      { to: '/alerts',     label: 'Алерты',     icon: AlertCircle,                roles: ALL },
    ],
  },
  {
    id: 'upload',
    label: 'Загрузка',
    icon: Upload,
    items: [
      { to: '/upload',         label: 'Загрузка XLSX', icon: Upload,    roles: ALL },
      { to: '/primary-data',   label: 'Первичка',      icon: FileUp,    roles: ALL },
      { to: '/reconciliation', label: 'Сверка',        icon: CheckCircle, roles: ALL },
      { to: '/history',        label: 'История',       icon: History,   roles: ALL },
      { to: '/import',         label: 'Импорт истории',icon: Database,  roles: ['admin'] },
    ],
  },
  {
    id: 'reports',
    label: 'Отчёты',
    icon: FileText,
    items: [
      { to: '/reports',     label: 'Сводные отчёты', icon: FileText,   roles: ALL },
      { to: '/positions',   label: 'Позиции',        icon: Table2,     roles: ALL },
      { to: '/securities',  label: 'Справочник ЦБ',  icon: BookMarked, roles: ALL },
      { to: '/risk-report', label: 'Risk Report',    icon: ShieldAlert,roles: ALL },
      { to: '/kase',        label: 'KASE',           icon: TrendingUp, roles: ALL },
      { to: '/mbm',         label: 'MBM',            icon: Activity,   roles: ALL },
    ],
  },
  {
    id: 'settings',
    label: 'Настройки',
    icon: Settings,
    items: [
      { to: '/settings',    label: 'ЧДУ и лимиты',  icon: Settings,       roles: NON_AUDITOR },
      { to: '/data-editor', label: 'Редактор БД',   icon: Pencil,         roles: ['admin', 'analyst'] },
      { to: '/formulas',    label: 'Формулы',       icon: FunctionSquare, roles: ['admin'] },
      { to: '/admin',       label: 'Пользователи', icon: Users,          roles: ['admin'] },
    ],
  },
]

const filterItems = (items: NavItem[], role: Role | null): NavItem[] => {
  if (!role) return []
  return items.filter((item) => {
    if (item.roles && !item.roles.includes(role)) return false
    if (role === 'operator' && !OPERATOR_VISIBLE.has(item.to)) return false
    return true
  })
}

const ROLE_BADGE: Record<Role, string> = {
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
  // If a child route becomes active later (e.g. via URL change), keep the
  // group open so the active link stays visible.
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
  const clear = useAuthStore((s) => s.clear)
  const nav = useNavigate()
  const { pathname } = useLocation()

  const handleLogout = () => {
    clear()
    nav('/login', { replace: true })
  }

  // Filter groups by role, dropping any that became empty.
  const groupsForRole = useMemo(() => {
    return navGroups
      .map((g) => ({ group: g, items: filterItems(g.items, role) }))
      .filter((g) => g.items.length > 0)
  }, [role])

  // A group is open by default if it contains the currently active route.
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
            {role ? ROLE_BADGE[role] : '—'}
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
