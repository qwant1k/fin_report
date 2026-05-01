import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AuthState {
  token: string | null
  role: string | null
  fullName: string | null
  setSession: (token: string, role: string, fullName: string | null) => void
  clear: () => void
  isAuthed: () => boolean
  isAdmin: () => boolean
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      role: null,
      fullName: null,
      setSession: (token, role, fullName) => set({ token, role, fullName }),
      clear: () => set({ token: null, role: null, fullName: null }),
      isAuthed: () => !!get().token,
      isAdmin: () => get().role === 'admin',
    }),
    { name: 'kdif-auth' },
  ),
)
