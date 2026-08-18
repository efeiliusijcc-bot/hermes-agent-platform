import axios, { AxiosError } from 'axios'
import { getManagementKey } from './managementKey'

interface FastAPIErrorBody {
  detail?: string | Array<{ loc?: Array<string | number>; msg?: string }>
}

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/',
  timeout: 300_000,
  headers: { Accept: 'application/json' },
})

apiClient.interceptors.request.use((config) => {
  const key = getManagementKey()
  if (key) config.headers.set('X-Platform-Management-Key', key)
  return config
})

export function getApiErrorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) {
    return error instanceof Error ? error.message : '发生未知错误'
  }

  if (error.code === 'ECONNABORTED') return '请求超时，请检查 Hermes Runtime 或模型服务状态'
  if (!error.response) return '无法连接后端，请检查 Agent API 是否可用'

  const body = error.response.data as FastAPIErrorBody | undefined
  if (typeof body?.detail === 'string') return body.detail
  if (Array.isArray(body?.detail)) {
    return body.detail
      .map((item) => `${item.loc?.slice(1).join('.') || '字段'}: ${item.msg || '校验失败'}`)
      .join('；')
  }
  return `请求失败（HTTP ${error.response.status}）`
}
