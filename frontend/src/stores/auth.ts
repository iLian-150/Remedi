import { defineStore } from 'pinia'
import type { User } from '../api/types'

// 登录态：Pinia + localStorage 持久化
// 契约：POST /api/auth/login {username, role} -> {token, token_type, user:{id,name,student_no,role}}
interface AuthState {
  token: string
  user: User | null
  activeSubject: string
}

const SESSION_KEYS = ['remedi_token', 'remedi_user', 'remedi_active_subject']
const SUBJECTS = new Set([
  'chinese', 'math', 'english', 'politics', 'history', 'physics', 'chemistry', 'geography', 'biology'
])

function clearStoredSession() {
  for (const key of SESSION_KEYS) {
    try { localStorage.removeItem(key) } catch { /* 存储被禁用时仍可退出内存会话。 */ }
  }
}

function parseStoredUser(value: unknown): User | null {
  if (!value || typeof value !== 'object') return null
  const user = value as Record<string, unknown>
  if (typeof user.id !== 'number' || !Number.isSafeInteger(user.id) || user.id <= 0
    || typeof user.name !== 'string' || !user.name.trim()
    || (user.role !== 'teacher' && user.role !== 'student')
    || (user.student_no != null && typeof user.student_no !== 'string')
    || (user.created_at != null && typeof user.created_at !== 'string')) return null
  return {
    id: user.id, name: user.name, role: user.role,
    student_no: typeof user.student_no === 'string' ? user.student_no : null,
    ...(typeof user.created_at === 'string' ? { created_at: user.created_at } : {})
  }
}

function restoreSession(): AuthState {
  const empty: AuthState = { token: '', user: null, activeSubject: '' }
  try {
    const token = localStorage.getItem('remedi_token')?.trim() || ''
    const raw = localStorage.getItem('remedi_user')
    const user = raw ? parseStoredUser(JSON.parse(raw)) : null
    if (!token || !user) {
      clearStoredSession()
      return empty
    }
    const storedSubject = localStorage.getItem('remedi_active_subject') || ''
    const activeSubject = user.role === 'teacher' && SUBJECTS.has(storedSubject) ? storedSubject : ''
    if (storedSubject && !activeSubject) {
      try { localStorage.removeItem('remedi_active_subject') } catch { /* 内存中仍使用已校验的学科。 */ }
    }
    return { token, user, activeSubject }
  } catch {
    clearStoredSession()
    return empty
  }
}

export const useAuthStore = defineStore('auth', {
  state: restoreSession,
  getters: {
    role: (s): 'teacher' | 'student' | '' => s.user?.role ?? '',
    name: (s): string => s.user?.name ?? ''
  },
  actions: {
    setSession(token: string, user: User, activeSubject = '') {
      this.token = token
      this.user = user
      this.activeSubject = activeSubject
      try {
        localStorage.setItem('remedi_token', token)
        localStorage.setItem('remedi_user', JSON.stringify(user))
        if (activeSubject) localStorage.setItem('remedi_active_subject', activeSubject)
        else localStorage.removeItem('remedi_active_subject')
      } catch {
        // 写入失败时清除部分缓存，当前页面继续使用已建立的内存会话。
        clearStoredSession()
      }
    },
    logout() {
      this.token = ''
      this.user = null
      this.activeSubject = ''
      clearStoredSession()
    }
  }
})
