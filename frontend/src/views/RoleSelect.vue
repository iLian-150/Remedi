<!-- 角色选择 + mock 登录页
     契约：POST /api/auth/login {username, role} -> {token, token_type, user}，用户不存在自动创建
     保留一键角色切换：切换角色即预填演示账号，一键进入，方便演示完整闭环 -->
<template>
  <div class="page login-page">
    <div class="card login-card">
      <h2>Remedi</h2>
      <p class="subtitle">多学科智能作业批改与学习诊断系统</p>

      <div class="form-row">
        <label>我是</label>
        <div class="role-btns">
          <button :class="['btn', role === 'teacher' ? '' : 'secondary']" @click="switchRole('teacher')">👩‍🏫 教师</button>
          <button :class="['btn', role === 'student' ? '' : 'secondary']" @click="switchRole('student')">🎒 学生</button>
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
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import api from '../api/client'
import type { LoginResponse } from '../api/types'

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
    router.push(role.value === 'teacher' ? '/teacher/dashboard' : '/student/assignments')
  } catch (e: unknown) {
    error.value = '登录失败，请稍后重试；若持续失败请联系管理员检查后端服务。'
    console.error(e)
  } finally {
    loading.value = false
  }
}
</script>
