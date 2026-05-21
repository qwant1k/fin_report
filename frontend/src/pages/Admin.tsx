import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { UserPlus, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { formatDate } from '@/lib/format'

interface User {
  id: number
  username: string
  full_name: string | null
  email: string | null
  role: string
  is_active: boolean
  created_at: string
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

export default function AdminPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<'users' | 'audit'>('users')
  const users = useQuery<User[]>({
    queryKey: ['users'],
    queryFn: async () => (await api.get('/admin/users')).data,
  })
  const audit = useQuery<AuditEntry[]>({
    queryKey: ['audit'],
    queryFn: async () => (await api.get('/admin/audit')).data,
  })

  const [newUser, setNewUser] = useState({
    username: '', password: '', full_name: '', email: '', role: 'viewer',
  })

  const create = useMutation({
    mutationFn: async () => (await api.post('/admin/users', newUser)).data,
    onSuccess: () => {
      toast.success('Пользователь создан')
      setNewUser({ username: '', password: '', full_name: '', email: '', role: 'viewer' })
      qc.invalidateQueries({ queryKey: ['users'] })
    },
  })

  const remove = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/admin/users/${id}`)).data,
    onSuccess: () => {
      toast.success('Удалено')
      qc.invalidateQueries({ queryKey: ['users'] })
    },
  })

  const setRole = useMutation({
    mutationFn: async ({ id, role }: { id: number; role: string }) =>
      (await api.put(`/admin/users/${id}/role`, null, { params: { role } })).data,
    onSuccess: () => {
      toast.success('Роль обновлена')
      qc.invalidateQueries({ queryKey: ['users'] })
    },
  })

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Администрирование</h1>
        <p className="text-sm text-slate-500">Пользователи и аудит-лог</p>
      </header>

      <div className="flex gap-2 border-b border-slate-200">
        <button onClick={() => setTab('users')} className={`px-4 py-2 ${tab === 'users' ? 'border-b-2 border-kdif-green text-kdif-green font-semibold' : 'text-slate-500'}`}>Пользователи</button>
        <button onClick={() => setTab('audit')} className={`px-4 py-2 ${tab === 'audit' ? 'border-b-2 border-kdif-green text-kdif-green font-semibold' : 'text-slate-500'}`}>Аудит</button>
      </div>

      {tab === 'users' && (
        <>
          <div className="card p-4 space-y-3">
            <h2 className="font-semibold">Новый пользователь</h2>
            <div className="grid grid-cols-1 md:grid-cols-6 gap-2">
              <input className="input" placeholder="Логин" value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} />
              <input className="input" placeholder="Пароль" type="password" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} />
              <input className="input" placeholder="ФИО" value={newUser.full_name} onChange={(e) => setNewUser({ ...newUser, full_name: e.target.value })} />
              <input className="input" placeholder="Email" value={newUser.email} onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} />
              <select className="input" value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}>
                <option value="auditor">auditor</option>
                <option value="operator">operator</option>
                <option value="analyst">analyst</option>
                <option value="admin">admin</option>
              </select>
              <button onClick={() => create.mutate()} className="btn-primary">
                <UserPlus className="w-4 h-4" /> Добавить
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
                      <td>{u.full_name ?? '—'}</td>
                      <td>{u.email ?? '—'}</td>
                      <td>
                        <select className="input py-1" value={u.role} onChange={(e) => setRole.mutate({ id: u.id, role: e.target.value })}>
                          <option value="auditor">auditor</option>
                          <option value="operator">operator</option>
                          <option value="analyst">analyst</option>
                          <option value="admin">admin</option>
                          <option value="viewer">viewer (legacy)</option>
                        </select>
                      </td>
                      <td>{formatDate(u.created_at)}</td>
                      <td>
                        <button onClick={() => remove.mutate(u.id)} className="btn-secondary text-red-600 px-2 py-1">
                          <Trash2 className="w-4 h-4" />
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

      {tab === 'audit' && (
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
                    <td>{a.user ?? '—'}</td>
                    <td>{a.action}</td>
                    <td>{a.entity ?? '—'}</td>
                    <td>{a.entity_id ?? '—'}</td>
                    <td className="text-xs">{a.details ?? '—'}</td>
                  </tr>
                ))}
                {!audit.data?.length && <tr><td colSpan={6} className="text-center text-slate-400 py-6">Лог пуст</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
