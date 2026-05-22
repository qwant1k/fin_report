import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Save, Shield, Trash2, UserPlus } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { formatDate } from '@/lib/format'

interface User {
  id: number
  username: string
  full_name: string | null
  email: string | null
  role: string
  is_active: boolean
  created_at: string
  permissions: string[]
}

interface AuditEntry {
  id: number
  ts: string
  user: string | null
  action: string
  entity: string | null
  entity_id: number | null
  details: string | null
}

interface PermissionItem {
  code: string
  group: string
  label: string
}

interface RoleDefinition {
  id: number
  code: string
  name: string
  description: string | null
  permissions: string[]
  is_system: boolean
  is_active: boolean
  created_at: string
  updated_at: string
}

interface RoleForm {
  id: number | null
  code: string
  name: string
  description: string
  permissions: string[]
  is_active: boolean
  is_system: boolean
}

type AdminTab = 'users' | 'roles' | 'audit'

const emptyRoleForm: RoleForm = {
  id: null,
  code: '',
  name: '',
  description: '',
  permissions: [],
  is_active: true,
  is_system: false,
}

export default function AdminPage() {
  const qc = useQueryClient()
  const token = useAuthStore((s) => s.token)
  const setSession = useAuthStore((s) => s.setSession)
  const canManageUsers = useAuthStore((s) => s.can('admin.users.manage'))
  const canManageRoles = useAuthStore((s) => s.can('admin.roles.manage'))
  const canViewAudit = useAuthStore((s) => s.can('admin.audit.view'))
  const [tab, setTab] = useState<AdminTab>('users')
  const [roleForm, setRoleForm] = useState<RoleForm>(emptyRoleForm)
  const [newUser, setNewUser] = useState({
    username: '', password: '', full_name: '', email: '', role: 'viewer',
  })

  const canLoadRoles = canManageUsers || canManageRoles

  const availableTabs = useMemo<AdminTab[]>(() => {
    const items: AdminTab[] = []
    if (canManageUsers) items.push('users')
    if (canManageRoles) items.push('roles')
    if (canViewAudit) items.push('audit')
    return items
  }, [canManageUsers, canManageRoles, canViewAudit])

  useEffect(() => {
    if (availableTabs.length > 0 && !availableTabs.includes(tab)) {
      setTab(availableTabs[0])
    }
  }, [availableTabs, tab])

  const refreshCurrentSession = async () => {
    if (!token) return
    const { data } = await api.get('/auth/me')
    setSession(token, data.role, data.full_name ?? null, data.permissions ?? [])
  }

  const users = useQuery<User[]>({
    queryKey: ['users'],
    queryFn: async () => (await api.get('/admin/users')).data,
    enabled: canManageUsers,
  })
  const roles = useQuery<RoleDefinition[]>({
    queryKey: ['roles'],
    queryFn: async () => (await api.get('/admin/roles')).data,
    enabled: canLoadRoles,
  })
  const permissions = useQuery<PermissionItem[]>({
    queryKey: ['permissions'],
    queryFn: async () => (await api.get('/admin/permissions')).data,
    enabled: canManageRoles,
  })
  const audit = useQuery<AuditEntry[]>({
    queryKey: ['audit'],
    queryFn: async () => (await api.get('/admin/audit')).data,
    enabled: canViewAudit,
  })

  const roleOptions = roles.data ?? []
  const activeRoles = roleOptions.filter((role) => role.is_active)

  const permissionsByGroup = useMemo(() => {
    const grouped = new Map<string, PermissionItem[]>()
    for (const item of permissions.data ?? []) {
      grouped.set(item.group, [...(grouped.get(item.group) ?? []), item])
    }
    return Array.from(grouped.entries())
  }, [permissions.data])

  const selectRole = (role: RoleDefinition) => {
    setRoleForm({
      id: role.id,
      code: role.code,
      name: role.name,
      description: role.description ?? '',
      permissions: role.permissions,
      is_active: role.is_active,
      is_system: role.is_system,
    })
  }

  const invalidateAdmin = () => {
    qc.invalidateQueries({ queryKey: ['users'] })
    qc.invalidateQueries({ queryKey: ['roles'] })
  }

  const createUser = useMutation({
    mutationFn: async () => (await api.post('/admin/users', newUser)).data,
    onSuccess: () => {
      toast.success('Пользователь создан')
      setNewUser({ username: '', password: '', full_name: '', email: '', role: 'viewer' })
      qc.invalidateQueries({ queryKey: ['users'] })
    },
  })

  const removeUser = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/admin/users/${id}`)).data,
    onSuccess: () => {
      toast.success('Пользователь удален')
      qc.invalidateQueries({ queryKey: ['users'] })
    },
  })

  const setRole = useMutation({
    mutationFn: async ({ id, role }: { id: number; role: string }) =>
      (await api.put(`/admin/users/${id}/role`, null, { params: { role } })).data,
    onSuccess: () => {
      toast.success('Роль пользователя обновлена')
      qc.invalidateQueries({ queryKey: ['users'] })
      void refreshCurrentSession()
    },
  })

  const saveRole = useMutation({
    mutationFn: async () => {
      const payload = {
        name: roleForm.name,
        description: roleForm.description || null,
        is_active: roleForm.is_active,
        ...(!roleForm.is_system ? { permissions: roleForm.permissions } : {}),
      }
      if (roleForm.id) {
        return (await api.patch(`/admin/roles/${roleForm.id}`, payload)).data
      }
      return (await api.post('/admin/roles', {
        code: roleForm.code,
        ...payload,
      })).data
    },
    onSuccess: (saved: RoleDefinition) => {
      toast.success('Роль сохранена')
      invalidateAdmin()
      selectRole(saved)
      void refreshCurrentSession()
    },
  })

  const removeRole = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/admin/roles/${id}`)).data,
    onSuccess: () => {
      toast.success('Роль удалена')
      setRoleForm(emptyRoleForm)
      invalidateAdmin()
      void refreshCurrentSession()
    },
  })

  const togglePermission = (code: string) => {
    setRoleForm((form) => ({
      ...form,
      permissions: form.permissions.includes(code)
        ? form.permissions.filter((item) => item !== code)
        : [...form.permissions, code],
    }))
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Администрирование</h1>
        <p className="text-sm text-slate-500">Пользователи, роли, права и аудит</p>
      </header>

      <div className="flex gap-2 border-b border-slate-200">
        {canManageUsers && <button onClick={() => setTab('users')} className={`px-4 py-2 ${tab === 'users' ? 'border-b-2 border-kdif-green text-kdif-green font-semibold' : 'text-slate-500'}`}>Пользователи</button>}
        {canManageRoles && <button onClick={() => setTab('roles')} className={`px-4 py-2 ${tab === 'roles' ? 'border-b-2 border-kdif-green text-kdif-green font-semibold' : 'text-slate-500'}`}>Роли и права</button>}
        {canViewAudit && <button onClick={() => setTab('audit')} className={`px-4 py-2 ${tab === 'audit' ? 'border-b-2 border-kdif-green text-kdif-green font-semibold' : 'text-slate-500'}`}>Аудит</button>}
      </div>

      {availableTabs.length === 0 && (
        <div className="card p-6 text-sm text-slate-500">
          Нет прав для управления пользователями, ролями или аудитом.
        </div>
      )}

      {tab === 'users' && canManageUsers && (
        <>
          <div className="card p-4 space-y-3">
            <h2 className="font-semibold">Новый пользователь</h2>
            <div className="grid grid-cols-1 gap-2 md:grid-cols-6">
              <input className="input" placeholder="Логин" value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} />
              <input className="input" placeholder="Пароль" type="password" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} />
              <input className="input" placeholder="ФИО" value={newUser.full_name} onChange={(e) => setNewUser({ ...newUser, full_name: e.target.value })} />
              <input className="input" placeholder="Email" value={newUser.email} onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} />
              <select className="input" value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}>
                {activeRoles.map((role) => (
                  <option key={role.code} value={role.code}>{role.name} ({role.code})</option>
                ))}
              </select>
              <button onClick={() => createUser.mutate()} className="btn-primary">
                <UserPlus className="h-4 w-4" /> Добавить
              </button>
            </div>
          </div>

          <div className="card overflow-hidden">
            <div className="table-wrap">
              <table className="kdif-table">
                <thead>
                  <tr><th>ID</th><th>Логин</th><th>ФИО</th><th>Email</th><th>Роль</th><th>Создан</th><th></th></tr>
                </thead>
                <tbody>
                  {(users.data ?? []).map((u) => (
                    <tr key={u.id}>
                      <td>{u.id}</td>
                      <td>{u.username}</td>
                      <td>{u.full_name ?? '-'}</td>
                      <td>{u.email ?? '-'}</td>
                      <td>
                        <select className="input py-1" value={u.role} onChange={(e) => setRole.mutate({ id: u.id, role: e.target.value })}>
                          {roleOptions.map((role) => (
                            <option key={role.code} value={role.code} disabled={!role.is_active}>
                              {role.name} ({role.code}){!role.is_active ? ' - отключена' : ''}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>{formatDate(u.created_at)}</td>
                      <td>
                        <button onClick={() => removeUser.mutate(u.id)} className="btn-secondary px-2 py-1 text-red-600">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {tab === 'roles' && canManageRoles && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[360px_1fr]">
          <div className="card overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-200 p-4">
              <h2 className="font-semibold">Роли</h2>
              <button className="btn-secondary h-9 px-3" onClick={() => setRoleForm(emptyRoleForm)}>
                <Plus className="h-4 w-4" /> Новая
              </button>
            </div>
            <div className="divide-y divide-slate-100">
              {roleOptions.map((role) => (
                <button
                  key={role.id}
                  type="button"
                  onClick={() => selectRole(role)}
                  className={`flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-slate-50 ${roleForm.id === role.id ? 'bg-emerald-50' : ''}`}
                >
                  <Shield className="mt-0.5 h-4 w-4 text-emerald-600" />
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold text-slate-800">{role.name}</span>
                    <span className="block truncate text-xs text-slate-500">{role.code}</span>
                    <span className="mt-1 block text-xs text-slate-400">
                      {role.permissions.length} прав{role.is_system ? ' - системная' : ''}{!role.is_active ? ' - отключена' : ''}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </div>

          <div className="card p-4">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="font-semibold">{roleForm.id ? 'Настройка роли' : 'Новая роль'}</h2>
                <p className="text-sm text-slate-500">Права можно настраивать до страницы и действия на кнопке.</p>
              </div>
              <div className="flex gap-2">
                {roleForm.id && !roleForm.is_system && (
                  <button className="btn-secondary text-red-600" onClick={() => removeRole.mutate(roleForm.id!)}>
                    <Trash2 className="h-4 w-4" /> Удалить
                  </button>
                )}
                <button className="btn-primary" onClick={() => saveRole.mutate()} disabled={!roleForm.name.trim() || (!roleForm.id && !roleForm.code.trim())}>
                  <Save className="h-4 w-4" /> Сохранить
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <label className="text-sm">
                <span className="label">Код роли</span>
                <input
                  className="input"
                  value={roleForm.code}
                  disabled={roleForm.id !== null}
                  placeholder="risk_manager"
                  onChange={(e) => setRoleForm({ ...roleForm, code: e.target.value })}
                />
              </label>
              <label className="text-sm">
                <span className="label">Название</span>
                <input className="input" value={roleForm.name} onChange={(e) => setRoleForm({ ...roleForm, name: e.target.value })} />
              </label>
              <label className="text-sm md:col-span-2">
                <span className="label">Описание</span>
                <textarea className="input min-h-[76px]" value={roleForm.description} onChange={(e) => setRoleForm({ ...roleForm, description: e.target.value })} />
              </label>
              <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
                <input
                  type="checkbox"
                  checked={roleForm.is_active}
                  disabled={roleForm.is_system}
                  onChange={(e) => setRoleForm({ ...roleForm, is_active: e.target.checked })}
                  className="h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                />
                Роль активна
              </label>
            </div>

            {roleForm.is_system && (
              <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                Системные роли синхронизируются приложением. Для кастомных прав создайте новую роль.
              </div>
            )}

            <div className="mt-5 space-y-4">
              {permissionsByGroup.map(([group, items]) => (
                <section key={group} className="rounded-md border border-slate-200 bg-white p-3">
                  <div className="mb-2 text-sm font-semibold text-slate-800">{group}</div>
                  <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
                    {items.map((permission) => (
                      <label key={permission.code} className="flex min-h-10 items-start gap-2 rounded-md border border-slate-100 px-2 py-2 text-sm hover:bg-slate-50">
                        <input
                          type="checkbox"
                          checked={roleForm.permissions.includes(permission.code)}
                          disabled={roleForm.is_system}
                          onChange={() => togglePermission(permission.code)}
                          className="mt-0.5 h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                        />
                        <span>
                          <span className="block font-medium text-slate-700">{permission.label}</span>
                          <span className="block text-xs text-slate-400">{permission.code}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </div>
        </div>
      )}

      {tab === 'audit' && canViewAudit && (
        <div className="card overflow-hidden">
          <div className="table-wrap">
            <table className="kdif-table">
              <thead>
                <tr><th>Время</th><th>Пользователь</th><th>Действие</th><th>Сущность</th><th>ID</th><th>Детали</th></tr>
              </thead>
              <tbody>
                {(audit.data ?? []).map((a) => (
                  <tr key={a.id}>
                    <td>{formatDate(a.ts)}</td>
                    <td>{a.user ?? '-'}</td>
                    <td>{a.action}</td>
                    <td>{a.entity ?? '-'}</td>
                    <td>{a.entity_id ?? '-'}</td>
                    <td className="text-xs">{a.details ?? '-'}</td>
                  </tr>
                ))}
                {!audit.data?.length && <tr><td colSpan={6} className="py-6 text-center text-slate-400">Лог пуст</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
