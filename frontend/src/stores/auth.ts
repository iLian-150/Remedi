import { defineStore } from 'pinia'
import type { User } from '../api/types'

// 登录态：Pinia + localStorage 持久化
// 契约：POST /api/auth/login {username, role} -> {token, token_type, user:{id,name,student_no,role}}
interface AuthState {
  token: string
  user: User | null
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => {
    const raw = localStorage.getItem('remedi_user')
    return {
      token: localStorage.getItem('remedi_token') || '',
      user: raw ? (JSON.parse(raw) as User) : null
    }
  },
  getters: {
    role: (s): 'teacher' | 'student' | '' => s.user?.role ?? '',
    name: (s): string => s.user?.name ?? ''
  },
  actions: {
    setSession(token: string, user: User) {
      this.token = token
      this.user = user
      localStorage.setItem('remedi_token', token)
      localStorage.setItem('remedi_user', JSON.stringify(user))
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('remedi_token')
      localStorage.removeItem('remedi_user')
    }
  }
})
