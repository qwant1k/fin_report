import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Role = 'admin' | 'analyst' | 'operator' | 'auditor' | 'viewer'

const WRITE_ROLES: Role[] = ['admin', 'analyst', 'operator']

interface AuthState {
  token: string | null
  role: Role | null
  fullName: string | null
  setSession: (token: string, role: string, fullName: string | null) => void
  clear: () => void
  isAuthed: () => boolean
  isAdmin: () => boolean
  isAnalyst: () => boolean
  isOperator: () => boolean
  isAuditor: () => boolean
  canWrite: () => boolean
}

const normaliseRole = (role: string | null): Role | null => {
  if (!role) return null
  return (['admin', 'analyst', 'operator', 'auditor', 'viewer'] as const).includes(role as Role)
    ? (role as Role)
    : 'viewer'
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      role: null,
      fullName: null,
      setSession: (token, role, fullName) =>
        set({ token, role: normaliseRole(role), fullName }),
      clear: () => set({ token: null, role: null, fullName: null }),
      isAuthed: () => !!get().token,
      isAdmin: () => get().role === 'admin',
      isAnalyst: () => get().role === 'analyst',
      isOperator: () => get().role === 'operator',
      isAuditor: () => get().role === 'auditor' || get().role === 'viewer',
      canWrite: () => {
        const r = get().role
        return r != null && WRITE_ROLES.includes(r)
      },
    }),
    { name: 'kdif-auth' },
  ),
)
