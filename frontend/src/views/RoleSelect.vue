<!-- 角色选择 + mock 登录页
     契约：POST /api/auth/login {username, role} -> {token, token_type, user}，用户不存在自动创建
     保留一键角色切换：切换角色即预填演示账号，一键进入，方便演示完整闭环 -->
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
      <div class="card login-card">
        <h2>欢迎回来</h2>
        <p class="subtitle">选择身份，输入用户名即可进入</p>

        <div class="form-row">
          <label>我是</label>
          <div class="role-btns">
            <button :class="['btn', 'inline-icon', role === 'teacher' ? '' : 'secondary']" @click="switchRole('teacher')"><AppIcon name="cap" :size="18" /> 教师</button>
            <button :class="['btn', 'inline-icon', role === 'student' ? '' : 'secondary']" @click="switchRole('student')"><AppIcon name="book" :size="18" /> 学生</button>
          </div>
        </div>

        <div class="form-row">
          <label>用户名</label>
          <input v-model="username" type="text" :placeholder="role === 'teacher' ? '例如：陈老师' : '例如：林小夏'" />
        </div>

        <div v-if="error" class="error-msg">{{ error }}</div>

        <button class="btn full" :disabled="loading" @click="login">
          {{ loading ? '登录中…' : '一键进入演示' }}
        </button>
        <p class="hint">MVP 演示登录：无需密码，不存在的用户名会自动创建。演示账号：教师「陈老师」、学生「林小夏」「陈默」。</p>
      </div>
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
const username = ref('林小夏')
const loading = ref(false)
const error = ref('')

// 一键角色切换：切换角色即预填对应演示账号
function switchRole(r: 'teacher' | 'student') {
  role.value = r
  username.value = r === 'teacher' ? '陈老师' : '林小夏'
  error.value = ''
}

async function login() {
  if (!username.value.trim()) {
    error.value = '请输入用户名'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.post<LoginResponse>('/api/auth/login', {
      username: username.value.trim(),
      role: role.value
    })
    auth.setSession(data.token, data.user)
    router.push(role.value === 'teacher' ? '/teacher/dashboard' : '/student/chat')
  } catch (e: unknown) {
    error.value = '登录失败，请稍后重试；若持续失败请联系管理员检查后端服务。'
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
