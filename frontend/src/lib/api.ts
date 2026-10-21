import axios, { AxiosError, AxiosResponse } from 'axios'
import toast from 'react-hot-toast'

import { useAuthStore } from './auth'

function resolveApiBaseURL() {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim()
  if (configured) return configured.replace(/\/+$/, '')

  if (import.meta.env.DEV && typeof window !== 'undefined') {
    const { hostname, port } = window.location
    const isLoopback = hostname === 'localhost' || hostname === '127.0.0.1'
    const isVitePort = port === '5173' || port === '5174'

    if (isLoopback && port && !isVitePort) {
      return `http://${hostname}:8000/api`
    }
  }

  return '/api'
}

export const api = axios.create({
  baseURL: resolveApiBaseURL(),
  timeout: 60_000,
})

api.interceptors.request.use((cfg) => {
  const token = useAuthStore.getState().token
  if (token) {
    cfg.headers = cfg.headers ?? {}
    cfg.headers.Authorization = `Bearer ${token}`
  }
  return cfg
})

api.interceptors.response.use(
  (resp: AxiosResponse) => resp,
  (err: AxiosError<{ detail?: unknown }>) => {
    const status = err.response?.status
    if (status === 401 && useAuthStore.getState().token) {
      useAuthStore.getState().clear()
      toast.error('Сессия истекла. Войдите в систему повторно.')
    }
    // Остальные ошибки обрабатывает конкретный экран: так сообщение содержит
    // контекст действия и не дублируется вторым уведомлением.
    return Promise.reject(err)
  },
)
