import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// 所有后端地址可通过 .env 配置（VITE_API_BASE_URL）。
// 开发默认：/api 由 vite 代理到后端 8000 端口。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiBase = env.VITE_API_BASE_URL || ''
  const backendTarget = env.VITE_BACKEND_TARGET || 'http://localhost:8000'

  return {
    plugins: [vue()],
    server: {
      port: 5173,
      proxy: apiBase
        ? undefined
        : {
            '/api': {
              target: backendTarget,
              changeOrigin: true
            }
          }
    }
  }
})
