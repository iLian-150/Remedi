<!-- 角色选择 + 无密码测试登录：学生使用名册姓名和学号，教师选择任教学科。 -->
<template>
  <div class="page login-page">
    <div class="login-layout">
      <!-- 左：品牌区（桌面分栏；移动端收成顶部横幅） -->
      <aside class="login-brand">
        <div class="login-brand-top">
          <span class="login-logo-badge"><BrandLogo :size="44" /></span>
          <div>
            <h1 class="login-brand-name">Remedi</h1>
            <p class="login-brand-sub">多学科智能作业批改与学习诊断系统</p>
          </div>
        </div>
        <p class="login-tagline">批改只是入口，修复才是目的。</p>
        <ul class="login-points">
          <li>
            <span class="login-point-icon"><AppIcon name="camera" :size="17" /></span>
            <span><b>拍照批改</b> —— 拍下手写过程，逐步检查每一步</span>
          </li>
          <li>
            <span class="login-point-icon"><AppIcon name="target" :size="17" /></span>
            <span><b>错因诊断</b> —— 定位第一步错在哪，并追问你先想一想</span>
          </li>
          <li>
            <span class="login-point-icon"><AppIcon name="chart" :size="17" /></span>
            <span><b>学习记忆</b> —— 订正再验证，见证每个知识点被修复</span>
          </li>
        </ul>
      </aside>

      <!-- 右：登录卡 -->
      <form class="card login-card" :aria-busy="loading" @submit.prevent="login">
        <h2>欢迎回来</h2>
        <p class="subtitle">教师选择任教学科；学生使用班级名册中的姓名和学号登录。</p>

        <div class="form-row">
          <label>我是</label>
          <div class="role-btns">
            <button type="button" :class="['btn', 'inline-icon', role === 'teacher' ? '' : 'secondary']" :disabled="loading" @click="switchRole('teacher')"><AppIcon name="cap" :size="18" /> 教师</button>
            <button type="button" :class="['btn', 'inline-icon', role === 'student' ? '' : 'secondary']" :disabled="loading" @click="switchRole('student')"><AppIcon name="book" :size="18" /> 学生</button>
          </div>
        </div>

        <div v-if="role === 'student'" class="form-row">
          <label>学生姓名</label>
          <input v-model="username" type="text" :disabled="loading" placeholder="按班级名册填写" />
        </div>

        <div v-if="role === 'student'" class="form-row">
          <label>学号</label>
          <input v-model="studentNo" type="text" :disabled="loading" placeholder="输入班级名册中的学号" />
        </div>
        <div v-else class="form-row">
          <label>任教学科</label>
          <select v-model="teacherSubject" :disabled="loading">
            <option v-for="item in subjects" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </div>

        <div v-if="error" class="error-msg">{{ error }}</div>

        <button type="submit" class="btn full" :disabled="loading">
          {{ loading ? '登录中…' : '一键进入演示' }}
        </button>
        <p class="hint">测试版免密码。学生账号由任课老师录入班级名册；姓名可重复，学号必须唯一。</p>
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
    await router.push(data.user.role === 'teacher' ? '/teacher/dashboard' : '/student/chat')
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
/* v0.4.0：登录页左右分栏（左品牌区 / 右登录卡），移动端单列 */
.login-page {
  display: flex; align-items: center; justify-content: center;
  min-height: 100dvh; padding: 32px 24px;
}
.login-layout {
  display: grid; grid-template-columns: 1.05fr 1fr;
  width: min(960px, 100%);
  background: var(--card); border: 1px solid #EDF0F4; border-radius: 20px;
  box-shadow: var(--shadow-lg); overflow: hidden;
}
.login-brand {
  background: linear-gradient(155deg, #2563EB 0%, var(--primary) 45%, #1E3A8A 100%);
  color: #fff; padding: 42px 40px;
  display: flex; flex-direction: column;
}
.login-brand-top { display: flex; align-items: center; gap: 16px; }
.login-logo-badge {
  width: 68px; height: 68px; border-radius: 18px; flex-shrink: 0;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.28);
  display: flex; align-items: center; justify-content: center; color: #fff;
}
.login-brand-name { font-size: 34px; font-weight: 800; letter-spacing: 0.5px; line-height: 1.15; }
.login-brand-sub { font-size: 13px; color: rgba(255, 255, 255, 0.78); }
.login-tagline { font-size: 19px; font-weight: 700; margin: 40px 0 26px; letter-spacing: 0.3px; }
.login-points { list-style: none; display: flex; flex-direction: column; gap: 16px; margin-top: auto; }
.login-points li { display: flex; align-items: flex-start; gap: 11px; font-size: 14px; color: rgba(255, 255, 255, 0.88); }
.login-points b { color: #fff; }
.login-point-icon {
  width: 32px; height: 32px; border-radius: 9px; flex-shrink: 0;
  background: rgba(255, 255, 255, 0.14);
  display: flex; align-items: center; justify-content: center; color: #fff;
}
.login-card {
  width: auto; text-align: left; margin-bottom: 0;
  border: none; box-shadow: none; border-radius: 0;
  padding: 42px 40px;
  display: flex; flex-direction: column; justify-content: center;
}
.login-card h2 { font-size: 24px; color: var(--text); margin-bottom: 4px; }
.login-card .subtitle { margin-bottom: 26px; }
@media (max-width: 860px) {
  .login-page { padding: 18px 14px; align-items: flex-start; }
  .login-layout { grid-template-columns: 1fr; }
  .login-brand { padding: 24px 22px; }
  .login-tagline { margin: 20px 0 6px; font-size: 17px; }
  .login-points { display: none; }
  .login-card { padding: 26px 22px 30px; }
}
</style>
