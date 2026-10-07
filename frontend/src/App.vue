<!-- 全局布局（v0.2.0 侧栏外壳；v0.3.0 升三栏；v0.3.1 右栏按页面分工；v0.4.0 品牌 Logo + 导航图标动效）：
     左侧导航 / 中间内容 / 右侧栏。右栏内容随当前页变：
       - 学生主页等普通页 → 只放便利贴提醒（mode=notes）
       - 学生/教师作业列表页 → 只放日历（mode=calendar，与列表筛选联动）
       - 教师其他页面 → 不挂右栏
     右栏可收起：收起后内容区右上角出现悬浮按钮，图标随场景变
     （notes=邮件+未读角标；calendar=日历图标无角标），点它重新展开；
     展开状态存 localStorage（remedi-rail-open），首次默认展开，移动端默认收起（抽屉式）。
     未登录只渲染登录页。 -->
<template>
  <!-- 未登录：仅登录页 -->
  <router-view v-if="!auth.token" />

  <!-- 已登录：统一外壳 -->
  <div v-else class="app-shell">
    <!-- 移动端顶栏 -->
    <header class="mobile-topbar">
      <button class="icon-btn" title="菜单" @click="sidebarOpen = !sidebarOpen">
        <AppIcon name="menu" :size="22" />
      </button>
      <span class="mobile-brand"><BrandLogo :size="21" /> Remedi</span>
      <span class="mobile-role">{{ auth.role === 'teacher' ? '教师端' : '学生端' }}</span>
    </header>
    <div v-if="sidebarOpen" class="sidebar-mask" @click="sidebarOpen = false"></div>

    <aside class="app-sidebar" :class="{ open: sidebarOpen }">
      <div class="sidebar-brand-row">
        <span class="brand-badge"><BrandLogo :size="25" /></span>
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
          <span class="nav-ic" :class="`ni-${item.icon}`"><AppIcon :name="item.icon" :size="18" /></span> {{ item.label }}
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

    <!-- 右侧栏：有场景时才挂载；用 class 控制展开/收起动画 -->
    <aside
      v-if="railMode !== 'none'"
      class="app-rail"
      :class="{ closed: !railOpen }"
      :aria-hidden="!railOpen"
    >
      <RightRail
        :mode="railMode === 'calendar' ? 'calendar' : 'notes'"
        @close="setRail(false)"
        @unread-change="unreadCount = $event"
      />
    </aside>

    <!-- 收起态入口：图标随场景变（提醒场景=邮件+未读角标；日历场景=日历图标） -->
    <button
      v-if="railMode !== 'none' && !railOpen"
      class="mail-fab"
      :class="{ 'has-unread': railMode === 'notes' && unreadCount > 0 }"
      :title="railMode === 'notes' ? '打开提醒' : '打开日历'"
      @click="setRail(true)"
    >
      <AppIcon :name="railMode === 'notes' ? 'mail' : 'calendar'" :size="20" />
      <span v-if="railMode === 'notes' && unreadCount > 0" :key="unreadCount" class="mail-badge">{{ unreadCount }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useStudentStore } from './stores/student'
import { useTeacherStore } from './stores/teacher'
import AppIcon from './components/icons/AppIcon.vue'
import type { IconName } from './components/icons/paths'
import BrandLogo from './components/BrandLogo.vue'
import RightRail from './components/RightRail.vue'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
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
  // v0.6.0：AI 助手排第一位（教师登录默认落点仍为总览，不变）
  { to: '/teacher/chat', icon: 'sparkles', label: 'AI 助手' },
  { to: '/teacher/dashboard', icon: 'chart', label: '总览' },
  { to: '/teacher/submissions', icon: 'file', label: '批改' },
  { to: '/teacher/students', icon: 'users', label: '学生' },
  { to: '/teacher/assignments', icon: 'clipboard', label: '作业', exact: true },
  { to: '/teacher/assignments/new', icon: 'plus-circle', label: '发布作业' },
  { to: '/teacher/workbooks', icon: 'book', label: '我的练习' },
  { to: '/teacher/suggestions', icon: 'lightbulb', label: '教学建议' }
]

const navItems = computed<NavItem[]>(() => (auth.role === 'teacher' ? TEACHER_NAV : STUDENT_NAV))
const avatarLetter = computed(() => (auth.name ? auth.name.slice(0, 1) : 'R'))

// ---------- 右侧栏场景（v0.3.1）：按角色 + 当前路由决定 ----------
// 学生：作业列表页只放日历；其余页面（含主页对话页）只放便利贴提醒。
// 教师：仅作业管理页放日历；其余页面不挂右栏（教师无通知）。
type RailMode = 'notes' | 'calendar' | 'none'
const railMode = computed<RailMode>(() => {
  if (auth.role === 'teacher') {
    return route.path === '/teacher/assignments' ? 'calendar' : 'none'
  }
  return route.path === '/student/assignments' ? 'calendar' : 'notes'
})

// ---------- 右侧栏展开状态：localStorage 记忆，首次默认展开（窄屏默认收起） ----------
const RAIL_KEY = 'remedi-rail-open'
function initRail(): boolean {
  try {
    const saved = localStorage.getItem(RAIL_KEY)
    if (saved === '1') return true
    if (saved === '0') return false
  } catch {
    /* localStorage 不可用时走默认 */
  }
  return window.innerWidth >= 1200
}
const railOpen = ref(initRail())
const unreadCount = ref(0)

function setRail(open: boolean) {
  railOpen.value = open
  try {
    localStorage.setItem(RAIL_KEY, open ? '1' : '0')
  } catch {
    /* 忽略写入失败 */
  }
}

function logout() {
  // 退出时清掉双端的日历日期筛选，避免换人登录后残留旧筛选
  useStudentStore().setAssignmentDateFilter('')
  useTeacherStore().setAssignmentDateFilter('')
  auth.logout()
  router.push('/')
}
</script>
