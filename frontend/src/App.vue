<!-- 全局布局（v0.2.0 改版）：学生端与教师端共用 Muse 式侧栏外壳
     左侧栏：品牌 / 导航（SVG 图标）/ 底部当前用户卡；移动端收起为抽屉。
     未登录只渲染登录页。 -->
<template>
  <!-- 未登录：仅登录页 -->
  <router-view v-if="!auth.token" />

  <!-- 已登录：统一侧栏外壳 -->
  <div v-else class="app-shell">
    <!-- 移动端顶栏 -->
    <header class="mobile-topbar">
      <button class="icon-btn" title="菜单" @click="sidebarOpen = !sidebarOpen">
        <AppIcon name="menu" :size="22" />
      </button>
      <span class="mobile-brand"><AppIcon name="sparkles" :size="18" /> Remedi</span>
      <span class="mobile-role">{{ auth.role === 'teacher' ? '教师端' : '学生端' }}</span>
    </header>
    <div v-if="sidebarOpen" class="sidebar-mask" @click="sidebarOpen = false"></div>

    <aside class="app-sidebar" :class="{ open: sidebarOpen }">
      <div class="sidebar-brand-row">
        <span class="brand-badge"><AppIcon name="sparkles" :size="20" /></span>
        <div>
          <div class="brand-name">Remedi</div>
          <div class="brand-sub">{{ auth.role === 'teacher' ? '教师端 · 班级诊断' : '智能作业诊断' }}</div>
        </div>
      </div>

      <nav class="sidebar-nav" @click="sidebarOpen = false">
        <router-link
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          :active-class="item.exact ? '' : 'active'"
          :exact-active-class="item.exact ? 'active' : ''"
        >
          <AppIcon :name="item.icon" :size="18" /> {{ item.label }}
        </router-link>
      </nav>

      <div class="sidebar-user">
        <span class="user-avatar">{{ avatarLetter }}</span>
        <div class="user-meta">
          <div class="user-name">{{ auth.name }}</div>
          <div class="user-role">
            {{ auth.role === 'teacher' ? '教师' : '学生' }}<template v-if="auth.user?.student_no"> · {{ auth.user.student_no }}</template>
          </div>
        </div>
        <button class="icon-btn" title="退出登录" @click="logout">
          <AppIcon name="logout" :size="18" />
        </button>
      </div>
    </aside>

    <main class="shell-main">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import AppIcon from './components/icons/AppIcon.vue'
import type { IconName } from './components/icons/paths'

const auth = useAuthStore()
const router = useRouter()
const sidebarOpen = ref(false)

interface NavItem {
  to: string
  icon: IconName
  label: string
  exact?: boolean
}

const STUDENT_NAV: NavItem[] = [
  { to: '/student/chat', icon: 'chat', label: '智能批改' },
  { to: '/student/assignments', icon: 'clipboard', label: '作业列表' },
  { to: '/student/submit', icon: 'edit', label: '交作业' },
  { to: '/student/feedback', icon: 'file', label: '诊断报告' },
  { to: '/student/report', icon: 'chart', label: '学习报告' },
  { to: '/student/corrections', icon: 'check', label: '订正错题' },
  { to: '/student/profile', icon: 'user', label: '我的档案' }
]

const TEACHER_NAV: NavItem[] = [
  { to: '/teacher/dashboard', icon: 'chart', label: '总览' },
  { to: '/teacher/submissions', icon: 'file', label: '批改' },
  { to: '/teacher/students', icon: 'users', label: '学生' },
  { to: '/teacher/assignments', icon: 'clipboard', label: '作业', exact: true },
  { to: '/teacher/assignments/new', icon: 'plus-circle', label: '发布作业' },
  { to: '/teacher/suggestions', icon: 'lightbulb', label: '教学建议' }
]

const navItems = computed<NavItem[]>(() => (auth.role === 'teacher' ? TEACHER_NAV : STUDENT_NAV))
const avatarLetter = computed(() => (auth.name ? auth.name.slice(0, 1) : 'R'))

function logout() {
  auth.logout()
  router.push('/')
}
</script>
