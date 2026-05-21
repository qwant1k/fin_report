import axios, { AxiosError, AxiosResponse } from 'axios'
import toast from 'react-hot-toast'

import { useAuthStore } from './auth'

export const api = axios.create({
  baseURL: '/api',
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
    const detail = err.response?.data?.detail
    if (status === 401) {
      useAuthStore.getState().clear()
      toast.error('Сессия истекла, войдите заново')
    } else if (status && status >= 500) {
      toast.error(typeof detail === 'string' ? detail : 'Ошибка сервера')
    } else if (typeof detail === 'string') {
      toast.error(detail)
    }
    // Structured detail objects (e.g. duplicate_file 409) are surfaced to the
    // caller so the UI can render its own dialog.
    return Promise.reject(err)
  },
)
