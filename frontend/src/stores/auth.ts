import { defineStore } from 'pinia'
import type { User } from '../api/types'

// 登录态：Pinia + localStorage 持久化
// 契约：POST /api/auth/login {username, role} -> {token, token_type, user:{id,name,student_no,role}}
interface AuthState {
  token: string
  user: User | null
  activeSubject: string
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => {
    const raw = localStorage.getItem('remedi_user')
    return {
      token: localStorage.getItem('remedi_token') || '',
      user: raw ? (JSON.parse(raw) as User) : null,
      activeSubject: localStorage.getItem('remedi_active_subject') || ''
    }
  },
  getters: {
    role: (s): 'teacher' | 'student' | '' => s.user?.role ?? '',
    name: (s): string => s.user?.name ?? ''
  },
  actions: {
    setSession(token: string, user: User, activeSubject = '') {
      this.token = token
      this.user = user
      this.activeSubject = activeSubject
      localStorage.setItem('remedi_token', token)
      localStorage.setItem('remedi_user', JSON.stringify(user))
      if (activeSubject) localStorage.setItem('remedi_active_subject', activeSubject)
      else localStorage.removeItem('remedi_active_subject')
    },
    logout() {
      this.token = ''
      this.user = null
      this.activeSubject = ''
      localStorage.removeItem('remedi_token')
      localStorage.removeItem('remedi_user')
      localStorage.removeItem('remedi_active_subject')
    }
  }
})
