import { useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Activity,
  Percent,
  AlertCircle,
  BookMarked,
  CalendarCheck,
  CalendarDays,
  CheckCircle,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Database,
  FileText,
  FunctionSquare,
  History,
  LayoutDashboard,
  LineChart,
  ListChecks,
  LogOut,
  Menu,
  Pencil,
  ReceiptText,
  Settings,
  ShieldAlert,
  Table2,
  TrendingUp,
  Upload,
  Users,
  X,
} from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'

import { cn } from '@/lib/cn'
import { useAuthStore } from '@/lib/auth'
import { todayIso, useWorkContextStore } from '@/lib/workContext'
import { ConfirmDialogHost } from '@/components/ui'
import UploadIndicator from '@/components/UploadIndicator'
import QuickApprovalDrawer from '@/components/QuickApprovalDrawer'

interface NavItem {
  to: string
  label: string
  icon: typeof LayoutDashboard
  /** Один пункт может быть доступен по любому из нескольких разрешений. */
  permission: string | string[]
  end?: boolean
}

interface NavGroup {
  id: string
  label: string
  icon: typeof LayoutDashboard
  items: NavItem[]
  defaultOpen?: boolean
  quiet?: boolean
}

const navGroups: NavGroup[] = [
  {
    id: 'portfolio-workspace',
    label: 'Портфель',
    icon: LayoutDashboard,
    defaultOpen: true,
    items: [
      { to: '/', label: 'Рабочий день', icon: CalendarCheck, permission: 'page.dashboard', end: true },
      { to: '/dashboard', label: 'Сводка', icon: LayoutDashboard, permission: 'page.dashboard' },
      { to: '/positions', label: 'Позиции', icon: Table2, permission: 'page.positions' },
      { to: '/operations', label: 'Операции', icon: ListChecks, permission: 'page.history' },
      { to: '/accounting', label: 'Операционный учёт', icon: ReceiptText, permission: 'page.accounting' },
      { to: '/analytics', label: 'Аналитика', icon: LineChart, permission: 'page.analytics' },
      { to: '/securities', label: 'Справочник ЦБ', icon: BookMarked, permission: 'page.securities' },
      { to: '/reports', label: 'Отчеты', icon: FileText, permission: 'page.reports' },
      { to: '/alerts', label: 'Алерты', icon: AlertCircle, permission: 'page.alerts' },
    ],
  },
  {
    id: 'data-flow',
    label: 'Данные',
    icon: Upload,
    items: [
      { to: '/documents', label: 'Загрузка документов', icon: Upload, permission: ['page.upload', 'page.primary_data'] },
      { to: '/reconciliation', label: 'Сверка', icon: CheckCircle, permission: 'page.reconciliation' },
      { to: '/risk-report', label: 'Отчёт о рисках', icon: ShieldAlert, permission: 'page.risk_report' },
      { to: '/history', label: 'История загрузок', icon: History, permission: 'page.history' },
      { to: '/import', label: 'Импорт истории', icon: Database, permission: 'page.import' },
    ],
  },
  {
    id: 'market',
    label: 'Рынок',
    icon: TrendingUp,
    items: [
      { to: '/kase', label: 'Цены KASE', icon: TrendingUp, permission: 'page.kase' },
      { to: '/mbm', label: 'MBM', icon: Activity, permission: 'page.mbm' },
      { to: '/tonia', label: 'TONIA Compounded', icon: Percent, permission: 'page.kase' },
    ],
  },
  {
    id: 'settings',
    label: 'Администрирование',
    icon: Settings,
    quiet: true,
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
  onNavigate?: () => void
}

function NavGroupBlock({ group, items, initiallyOpen, onNavigate }: NavGroupBlockProps) {
  const [open, setOpen] = useState(initiallyOpen || !!group.defaultOpen)

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
        className={cn(
          'flex w-full items-center justify-between rounded-xl px-3 py-2 text-sm font-semibold transition',
          group.quiet ? 'text-slate-400 hover:bg-white/10 hover:text-slate-200' : 'text-slate-200 hover:bg-white/10',
          initiallyOpen && 'text-emerald-300',
        )}
      >
        <span className="flex items-center gap-3">
          <Icon className="h-4 w-4" />
          {group.label}
        </span>
        <ChevronDown
          className={cn('h-4 w-4 shrink-0 transition-transform duration-300', open ? 'rotate-0' : '-rotate-90')}
        />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div className="ml-3 mt-1 space-y-0.5 border-l border-white/10 pl-3">
              {items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    cn(
                      'group/nav relative flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition',
                      isActive
                        ? 'bg-brand-gradient text-white shadow-sm shadow-emerald-950/30'
                        : 'text-slate-300 hover:bg-white/10 hover:text-white',
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      {isActive && (
                        <motion.span
                          layoutId="nav-active-dot"
                          className="absolute -left-[15px] h-5 w-1 rounded-full bg-emerald-300"
                          transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                        />
                      )}
                      <item.icon className="h-4 w-4 shrink-0 transition-transform group-hover/nav:scale-110" />
                      {item.label}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

interface SidebarBodyProps {
  groupsForRole: { group: NavGroup; items: NavItem[] }[]
  isGroupActive: (items: NavItem[]) => boolean
  fullName: string | null
  role: string | null
  onLogout: () => void
  onNavigate?: () => void
}

function initials(name: string | null): string {
  if (!name) return 'U'
  const parts = name.trim().split(/\s+/).slice(0, 2)
  return parts.map((p) => p[0]?.toUpperCase() ?? '').join('') || 'U'
}

function SidebarBody({ groupsForRole, isGroupActive, fullName, role, onLogout, onNavigate }: SidebarBodyProps) {
  return (
    <div className="flex h-full flex-col bg-gradient-to-b from-slate-900 via-slate-950 to-slate-950 text-white">
      <div className="border-b border-white/10 p-5">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-gradient text-base font-black text-white shadow-glow">
            К
          </div>
          <div>
            <div className="font-display text-lg font-bold leading-tight">КФГД</div>
            <div className="mt-0.5 text-xs font-medium text-emerald-200/70">Fund Reporting</div>
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
            onNavigate={onNavigate}
          />
        ))}
      </nav>

      <div className="border-t border-white/10 p-3">
        <div className="mb-3 flex items-center gap-3 rounded-xl bg-white/5 p-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-gradient text-sm font-bold text-white">
            {initials(fullName)}
          </div>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold">{fullName ?? 'Пользователь'}</div>
            <div className="truncate text-xs text-emerald-200/70">{role ? (ROLE_BADGE[role] ?? role) : '-'}</div>
          </div>
        </div>
        <button
          onClick={onLogout}
          className="btn w-full border border-white/10 bg-white/10 text-white hover:bg-white/20"
        >
          <LogOut className="h-4 w-4" />
          Выйти
        </button>
      </div>
    </div>
  )
}

// Экраны, где рабочая дата не имеет смысла (администрирование, справочники ролей и т.п.) —
// на них глобальная панель даты не показывается, чтобы не создавать ложный контекст.
const DATE_CONTEXT_HIDDEN_PREFIXES = ['/settings', '/data-editor', '/formulas', '/admin']

function WorkDateBar() {
  const { pathname } = useLocation()
  const workDate = useWorkContextStore((s) => s.workDate)
  const setWorkDate = useWorkContextStore((s) => s.setWorkDate)
  const shiftWorkDate = useWorkContextStore((s) => s.shiftWorkDate)

  if (DATE_CONTEXT_HIDDEN_PREFIXES.some((p) => pathname.startsWith(p))) {
    return (
      <div className="-mx-4 mb-4 flex justify-end border-b border-slate-200/80 bg-white/85 px-4 py-2.5 backdrop-blur-xl sm:-mx-5 sm:px-5 lg:sticky lg:top-0 lg:z-20 lg:-mx-8 lg:px-8">
        <QuickApprovalDrawer />
      </div>
    )
  }

  const isToday = workDate === todayIso()

  return (
    // Sticky только от lg и выше: на мобильных уже есть свой sticky-хедер (см. ниже),
    // и две прилипающие панели одновременно перекрывали бы друг друга.
    <div className="-mx-4 mb-4 flex flex-wrap items-center gap-2 border-b border-slate-200/80 bg-white/85 px-4 py-2.5 backdrop-blur-xl sm:-mx-5 sm:px-5 lg:sticky lg:top-0 lg:z-20 lg:-mx-8 lg:px-8">
      <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">
        <CalendarDays className="h-3.5 w-3.5" />
        Дата отчёта
      </span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => shiftWorkDate(-1)}
          className="rounded-lg p-1.5 text-slate-500 transition hover:bg-slate-100"
          aria-label="Предыдущий день"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <input
          type="date"
          value={workDate}
          onChange={(e) => setWorkDate(e.target.value)}
          className="input h-8 w-[9.5rem] px-2 py-0 text-sm"
        />
        <button
          type="button"
          onClick={() => shiftWorkDate(1)}
          className="rounded-lg p-1.5 text-slate-500 transition hover:bg-slate-100"
          aria-label="Следующий день"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
      {!isToday && (
        <button type="button" onClick={() => setWorkDate(todayIso())} className="control-chip h-8 px-2.5 text-xs">
          Сегодня
        </button>
      )}
      <div className="ml-auto flex items-center gap-2">
        <span className="hidden text-xs text-slate-400 xl:inline">
          Единый контекст для Рабочего дня, Позиций, KASE, Сверки и Отчётов
        </span>
        <QuickApprovalDrawer />
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
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    setMobileOpen(false)
  }, [pathname])

  const handleLogout = () => {
    clear()
    nav('/login', { replace: true })
  }

  const hasPermission = (permission: string | string[], current: Set<string>) =>
    Array.isArray(permission) ? permission.some((p) => current.has(p)) : current.has(permission)

  const groupsForRole = useMemo(() => {
    const current = new Set(permissions)
    return navGroups
      .map((group) => ({ group, items: group.items.filter((item) => hasPermission(item.permission, current)) }))
      .filter((group) => group.items.length > 0)
  }, [permissions])

  const isGroupActive = (items: NavItem[]) =>
    items.some((it) => (it.end ? pathname === it.to : pathname.startsWith(it.to)))

  const activeLabel = useMemo(() => {
    for (const { items } of groupsForRole) {
      const hit = items.find((it) => (it.end ? pathname === it.to : pathname.startsWith(it.to)))
      if (hit) return hit.label
    }
    return 'КФГД'
  }, [groupsForRole, pathname])

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 shadow-2xl shadow-slate-950/20 lg:block">
        <SidebarBody
          groupsForRole={groupsForRole}
          isGroupActive={isGroupActive}
          fullName={fullName}
          role={role}
          onLogout={handleLogout}
        />
      </aside>

      {/* Mobile drawer */}
      <AnimatePresence>
        {mobileOpen && (
          <div className="fixed inset-0 z-50 lg:hidden">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMobileOpen(false)}
              className="absolute inset-0 bg-slate-950/50 backdrop-blur-sm"
            />
            <motion.aside
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ type: 'spring', stiffness: 320, damping: 32 }}
              className="absolute left-0 top-0 h-full w-72 shadow-2xl"
            >
              <SidebarBody
                groupsForRole={groupsForRole}
                isGroupActive={isGroupActive}
                fullName={fullName}
                role={role}
                onLogout={handleLogout}
                onNavigate={() => setMobileOpen(false)}
              />
            </motion.aside>
          </div>
        )}
      </AnimatePresence>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile top bar */}
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-slate-200/80 bg-white/80 px-4 py-3 backdrop-blur-xl lg:hidden">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="rounded-lg p-2 text-slate-600 transition hover:bg-slate-100"
            aria-label="Меню"
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="flex items-center gap-2 font-display font-semibold text-slate-800">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-gradient text-xs font-black text-white">
              К
            </span>
            {activeLabel}
          </span>
        </header>

        <main className="min-w-0 flex-1 overflow-x-auto p-4 sm:p-5 lg:p-8">
          {/*
            Переход между страницами больше не анимируется (см. UX-аудит: анимация на
            каждый клик мешает операторам, ежедневно выполняющим одни и те же действия).
            Анимация оставлена только там, где она несёт смысл: прогресс, ошибки, подтверждения.
          */}
          <WorkDateBar />
          <Outlet />
        </main>
      </div>

      {/* Close icon helper kept for a11y on drawer (rendered within drawer when open) */}
      {mobileOpen && (
        <button
          type="button"
          onClick={() => setMobileOpen(false)}
          className="fixed right-4 top-4 z-[60] rounded-lg bg-white/10 p-2 text-white lg:hidden"
          aria-label="Закрыть меню"
        >
          <X className="h-5 w-5" />
        </button>
      )}

      {/* Единый диалог подтверждения критичных действий на всё приложение — см. lib/confirm.ts */}
      <ConfirmDialogHost />
      {/* Фоновая очередь загрузки документов — прогресс на любом экране */}
      <UploadIndicator />
    </div>
  )
}
