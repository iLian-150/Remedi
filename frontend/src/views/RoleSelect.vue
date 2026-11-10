<!-- 角色选择 + 无密码测试登录：学生使用名册姓名和学号，教师选择任教学科。 -->
<template>
  <div class="page login-page">
    <div class="login-layout">
      <!-- 品牌区 -->
      <aside class="login-brand">
        <div class="login-brand-top">
          <span class="login-logo-badge"><BrandLogo :size="46" /></span>
          <h1 class="login-brand-name">Remedi</h1>
        </div>
      </aside>

      <form class="card login-card" :aria-busy="loading" @submit.prevent="login">
        <h2>登录 Remedi</h2>
        <div class="form-row">
          <label>我是</label>
          <div class="role-btns" :class="`is-${role}`" role="group" aria-label="选择身份">
            <span class="role-indicator" aria-hidden="true"></span>
            <button type="button" class="btn inline-icon role-choice" :class="{ selected: role === 'teacher' }" :aria-pressed="role === 'teacher'" :disabled="loading" @click="switchRole('teacher')"><AppIcon name="cap" :size="18" /> 教师</button>
            <button type="button" class="btn inline-icon role-choice" :class="{ selected: role === 'student' }" :aria-pressed="role === 'student'" :disabled="loading" @click="switchRole('student')"><AppIcon name="book" :size="18" /> 学生</button>
          </div>
        </div>

        <Transition name="role-fields" mode="out-in">
          <div v-if="role === 'student'" key="student" class="role-fields">
            <div class="form-row">
              <label for="student-name">学生姓名</label>
              <input id="student-name" v-model="username" type="text" :disabled="loading" placeholder="按班级名册填写" autocomplete="off" />
            </div>
            <div class="form-row">
              <label for="student-number">学号</label>
              <input id="student-number" v-model="studentNo" type="text" :disabled="loading" placeholder="输入班级名册中的学号" autocomplete="off" />
            </div>
          </div>
          <div v-else key="teacher" class="role-fields">
            <div class="form-row">
              <label for="teacher-subject">任教学科</label>
              <select id="teacher-subject" v-model="teacherSubject" :disabled="loading">
                <option v-for="item in subjects" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </div>
          </div>
        </Transition>

        <div v-if="error" class="error-msg" role="alert">{{ error }}</div>

        <button type="submit" class="btn full" :disabled="loading">
          {{ loading ? '登录中…' : '进入系统' }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import api from '../api/client'
import type { LoginResponse } from '../api/types'
import AppIcon from '../components/icons/AppIcon.vue'
import BrandLogo from '../components/BrandLogo.vue'

const router = useRouter()
const auth = useAuthStore()

const role = ref<'teacher' | 'student'>('student')
const username = ref('')
const studentNo = ref('')
const teacherSubject = ref('math')
const subjects = [
  { value: 'chinese', label: '语文' }, { value: 'math', label: '数学' },
  { value: 'english', label: '英语' }, { value: 'politics', label: '道法' },
  { value: 'history', label: '历史' }, { value: 'physics', label: '物理' },
  { value: 'chemistry', label: '化学' }, { value: 'geography', label: '地理' },
  { value: 'biology', label: '生物' }
]
const loading = ref(false)
const error = ref('')

// 请求期间冻结登录身份；切换到学生时填写名册姓名和学号，教师只选择学科。
function switchRole(r: 'teacher' | 'student') {
  if (loading.value || r === role.value) return
  role.value = r
  username.value = ''
  studentNo.value = ''
  error.value = ''
}

async function login() {
  if (loading.value) return
  const payload = {
    role: role.value,
    username: role.value === 'student' ? username.value.trim() : undefined,
    student_no: role.value === 'student' ? studentNo.value.trim() : undefined,
    subject: role.value === 'teacher' ? teacherSubject.value : undefined
  }
  if (payload.role === 'student' && !payload.username) {
    error.value = '请输入学生姓名'
    return
  }
  if (payload.role === 'student' && !payload.student_no) {
    error.value = '请输入学号'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.post<LoginResponse>('/api/auth/login', payload)
    auth.setSession(data.token, data.user, data.active_subject ?? '')
    await router.replace(data.user.role === 'teacher' ? '/teacher/dashboard' : '/student/assignments')
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    error.value = typeof detail === 'string'
      ? detail
      : '登录失败，请稍后重试；若持续失败请联系管理员检查后端服务。'
    console.error(e)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex; align-items: center; justify-content: center;
  width: 100%; max-width: none; min-width: 0; min-height: 100dvh; padding: clamp(20px, 5vh, 48px) 24px;
}
.login-layout {
  display: grid; grid-template-columns: 0.9fr 1.1fr;
  width: min(940px, 100%); min-width: 0; min-height: 540px;
  background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-panel);
  box-shadow: var(--shadow-lg); overflow: hidden;
}
.login-layout > * { min-width: 0; }
.login-brand {
  display: flex; align-items: center; justify-content: center;
  background: var(--primary-50); color: var(--primary-dark); padding: 42px;
}
.login-brand-top { display: flex; align-items: center; gap: 15px; }
.login-logo-badge {
  width: 74px; height: 74px; border-radius: var(--radius-surface); flex-shrink: 0;
  background: #fff; border: 1px solid var(--blue-bg);
  display: flex; align-items: center; justify-content: center; color: var(--primary);
  box-shadow: var(--shadow);
}
.login-brand-name { font-size: clamp(34px, 4vw, 46px); font-weight: 780; letter-spacing: -0.045em; line-height: 1.1; }
.login-card {
  width: 100%; min-width: 0; text-align: left; margin-bottom: 0;
  border: none; box-shadow: none; border-radius: 0;
  padding: clamp(32px, 5vw, 58px);
  display: flex; flex-direction: column; justify-content: center;
}
.login-card h2 { font-size: 26px; color: var(--text); font-weight: 720; letter-spacing: -0.03em; margin-bottom: 28px; }
.login-card .form-row { margin-bottom: 20px; }
.login-card .form-row > label { font-size: 13px; color: var(--text-strong); }
.role-btns {
  position: relative; isolation: isolate;
  display: flex; gap: var(--control-inset); padding: var(--control-inset);
  border: 1px solid var(--border); border-radius: var(--radius-surface); background: var(--surface-2);
}
.role-indicator {
  position: absolute; z-index: 0; top: var(--control-inset); bottom: var(--control-inset);
  left: calc(var(--control-inset) + 1px); width: calc(50% - 7px);
  border: 1px solid var(--border); border-radius: var(--radius-control); background: var(--card); box-shadow: var(--shadow);
  transition: transform 0.36s cubic-bezier(0.2, 0.72, 0.25, 1);
}
.role-btns.is-student .role-indicator { transform: translateX(calc(100% + var(--control-inset))); }
.role-btns .role-choice {
  position: relative; z-index: 1; flex: 1; min-height: 42px; border: 1px solid transparent; border-radius: var(--radius-control);
  background: transparent; color: var(--text-2); box-shadow: none; transform: none;
  transition: color 0.2s ease;
}
.role-btns .role-choice.selected { background: transparent; border-color: transparent; color: var(--primary-dark); box-shadow: none; }
.role-btns .role-choice:disabled { opacity: 0.6; }
.role-fields-enter-active, .role-fields-leave-active { transition: opacity 0.2s ease, transform 0.24s cubic-bezier(0.2, 0.72, 0.25, 1); }
.role-fields-enter-from { opacity: 0; transform: translateY(8px); }
.role-fields-leave-to { opacity: 0; transform: translateY(-5px); }
@media (hover: hover) { .role-btns .role-choice:hover:not(:disabled) { background: transparent; color: var(--primary-dark); box-shadow: none; transform: none; } }
.login-card .full { margin-top: 4px; min-height: 48px; }
@media (prefers-reduced-motion: reduce) {
  .role-indicator, .role-fields-enter-active, .role-fields-leave-active { transition: none; }
}
@media (max-width: 760px) {
  .login-page { width: 100vw; max-width: 100vw; padding: 18px 14px; }
  .login-layout { grid-template-columns: 1fr; width: min(520px, calc(100vw - 28px)); min-height: 0; max-width: 520px; border-radius: var(--radius-panel); }
  .login-brand { justify-content: flex-start; padding: 24px 24px 18px; }
  .login-brand-top { gap: 11px; }
  .login-logo-badge { width: 46px; height: 46px; border-radius: var(--radius-control); box-shadow: none; }
  .login-logo-badge :deep(.brand-logo) { width: 30px; height: 30px; }
  .login-brand-name { font-size: 27px; }
  .login-card { padding: 26px 24px 28px; }
  .login-card h2 { font-size: 23px; margin-bottom: 22px; }
}
</style>
