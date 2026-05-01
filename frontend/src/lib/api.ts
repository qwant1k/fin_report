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
  (err: AxiosError<{ detail?: string }>) => {
    const status = err.response?.status
    if (status === 401) {
      useAuthStore.getState().clear()
      toast.error('Сессия истекла, войдите заново')
    } else if (status && status >= 500) {
      toast.error(err.response?.data?.detail ?? 'Ошибка сервера')
    } else if (err.response?.data?.detail) {
      toast.error(err.response.data.detail)
    }
    return Promise.reject(err)
  },
)
