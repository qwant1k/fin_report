import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Role = string

const WRITE_ROLES = ['admin', 'analyst', 'operator']
const WRITE_PERMISSIONS = [
  'dashboard.calculate',
  'reports.export',
  'reports.submit',
  'reports.approve',
  'reports.reject',
  'reports.regenerate',
  'reports.delete',
  'upload.trade_report',
  'primary_data.upload',
  'import.run',
  'reconciliation.run',
  'automation.run',
  'kase.refresh',
  'kase.reconcile',
  'kase.manual_price',
  'mbm.refresh',
  'mbm.manual',
  'settings.edit',
  'cdu_formats.edit',
  'formulas.edit',
  'data_editor.edit',
  'securities.edit',
  'risk_report.notes.edit',
  'admin.users.manage',
  'admin.roles.manage',
]

interface AuthState {
  token: string | null
  role: Role | null
  fullName: string | null
  permissions: string[]
  setSession: (token: string, role: string, fullName: string | null, permissions?: string[]) => void
  clear: () => void
  isAuthed: () => boolean
  isAdmin: () => boolean
  isAnalyst: () => boolean
  isOperator: () => boolean
  isAuditor: () => boolean
  can: (permission: string) => boolean
  canAny: (permissions: string[]) => boolean
  canWrite: () => boolean
}

const normaliseRole = (role: string | null): Role | null => {
  const value = role?.trim()
  return value || null
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      role: null,
      fullName: null,
      permissions: [],
      setSession: (token, role, fullName, permissions = []) =>
        set({ token, role: normaliseRole(role), fullName, permissions }),
      clear: () => set({ token: null, role: null, fullName: null, permissions: [] }),
      isAuthed: () => !!get().token,
      can: (permission) => get().permissions.includes(permission),
      canAny: (permissions) => permissions.some((permission) => get().permissions.includes(permission)),
      isAdmin: () => get().role === 'admin' || get().canAny(['admin.users.manage', 'admin.roles.manage']),
      isAnalyst: () => get().role === 'analyst',
      isOperator: () => get().role === 'operator',
      isAuditor: () => get().role === 'auditor' || get().role === 'viewer',
      canWrite: () => {
        const r = get().role
        return (r != null && WRITE_ROLES.includes(r)) || get().canAny(WRITE_PERMISSIONS)
      },
    }),
    { name: 'kdif-auth' },
  ),
)
