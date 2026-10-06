// axios 统一封装：
// 1. 从 Pinia auth store（localStorage 持久化）取 token，自动带 Authorization 头
// 2. baseURL 来自环境变量 VITE_API_BASE_URL（.env 可配置），默认走 /api 由 vite 代理
import axios from 'axios'
import { useAuthStore } from '../stores/auth'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30000
})

// 请求拦截器：自动带 token
api.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

// 响应拦截器：401 时清掉登录态并回到登录页
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      const auth = useAuthStore()
      auth.logout()
      if (window.location.pathname !== '/') {
        window.location.href = '/'
      }
    }
    return Promise.reject(err)
  }
)

export default api
