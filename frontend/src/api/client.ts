// axios 统一封装：
// 1. 从 Pinia auth store（localStorage 持久化）取 token，自动带 Authorization 头
// 2. baseURL 来自环境变量 VITE_API_BASE_URL（.env 可配置），默认空 = 同源相对路径
//    （各调用点路径已自带 /api 前缀；开发时由 vite 代理，部署时由 nginx 反代）
import axios from 'axios'
import { useAuthStore } from '../stores/auth'

const API_REQUEST_TIMEOUT_MS = 180_000

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: API_REQUEST_TIMEOUT_MS
})

// 请求拦截器：自动带 token
api.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

// 只有当前登录态发起的 401 才退出，避免旧请求在换人登录后清掉新会话。
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      const auth = useAuthStore()
      const requestAuthorization = err.config?.headers?.get?.('Authorization')
        ?? err.config?.headers?.Authorization
      const currentAuthorization = auth.token ? `Bearer ${auth.token}` : undefined
      if (requestAuthorization === currentAuthorization) {
        auth.logout()
        if (window.location.pathname !== '/') {
          window.location.href = '/'
        }
      }
    }
    return Promise.reject(err)
  }
)

export default api
