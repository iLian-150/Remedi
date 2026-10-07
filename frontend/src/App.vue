<!-- 全局布局（v0.2.0 侧栏外壳；v0.3.0 升三栏；v0.3.1 右栏按页面分工；v0.4.0 品牌 Logo + 导航图标动效）：
     左侧导航 / 中间内容 / 右侧栏。右栏内容随当前页变：
       - 学生主页等普通页 → 只放便利贴提醒（mode=notes）
       - 学生/教师作业列表页 → 只放日历（mode=calendar，与列表筛选联动）
       - 教师其他页面 → 不挂右栏
     右栏可收起：收起后内容区右上角出现场景专属悬浮按钮（notes=信封形 notes-fab + 未读角标，
     未读数读 student store；calendar=日历形 cal-fab，无角标），点它重新展开；
     展开状态按场景分键存 localStorage（remedi-rail-open-notes / remedi-rail-open-calendar），
     首次默认展开，移动端默认收起（抽屉式）。
     v0.6.2：双端对话页时左侧栏主导航下方多一段会话区（SidebarSessions，ChatGPT 式：
     新对话按钮 + 按今天/昨天/更早分组的会话列表）；移动端沿用抽屉不受影响。
     v0.8.2：全局侧栏成为双端唯一侧栏（学生对话页不再自带页内侧栏，统一走这里：
     会话区双端都挂 SidebarSessions、收起机制全角色一致）；未读数改由 student store 持有，
     进入学生任何页面（路由变化）时刷新一次。
     v0.9.0：侧栏收起改「图标轨」——不再整条消失，收起态宽 68px 只留 Logo 与导航图标
     （悬停 tooltip 显示标签）、头像与展开按钮（品牌行按钮图标随状态翻转），
     SidebarSessions / 品牌文字 / 账号文字在收起态隐藏；教师导航新增「待审核」
     （角标数读 teacher store，进教师端页面时刷新）。
     v0.9.1：学生订正页右栏切换为「订正日历」（mode=corrections，FAB 同样用 cal-fab）：
     按错题所属提交日期打点，点选日期 → store.correctionsDateFilter 生效 → 订正页
     只看那天的错题；订正页页内不再放日历（v0.9.0 曾在页内，统一迁入右栏）。
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

    <aside class="app-sidebar" :class="{ open: sidebarOpen, collapsed: sidebarCollapsed }">
      <div class="sidebar-brand-row">
        <span class="brand-badge"><BrandLogo :size="25" /></span>
        <div class="brand-text">
          <div class="brand-name">Remedi</div>
          <div class="brand-sub">{{ auth.role === 'teacher' ? '教师端 · 班级诊断' : '智能作业诊断' }}</div>
        </div>
        <button
          class="icon-btn sidebar-collapse-btn"
          :title="sidebarCollapsed ? '展开侧栏' : '收起侧栏'"
          @click="setSidebarCollapsed(!sidebarCollapsed)"
        >
          <AppIcon :name="sidebarCollapsed ? 'chevron-right' : 'panel-left'" :size="19" />
        </button>
      </div>

      <nav class="sidebar-nav" @click="sidebarOpen = false">
        <router-link
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          :data-label="item.label"
          :title="sidebarCollapsed ? undefined : item.label"
          :aria-label="item.label"
          :active-class="item.exact ? '' : 'active'"
          :exact-active-class="item.exact ? 'active' : ''"
        >
          <span class="nav-ic" :class="`ni-${item.icon}`"><AppIcon :name="item.icon" :size="18" /></span><span class="nav-label">{{ item.label }}</span><span v-if="item.badge" class="nav-badge tnum">{{ item.badge }}</span>
        </router-link>
      </nav>

      <!-- 会话区（v0.6.2；v0.8.2 起双端统一）：仅双端对话页出现；
           v0.9.0：桌面端侧栏收起成图标轨时由 style.css 隐藏（移动端抽屉不受影响） -->
      <SidebarSessions v-if="isChatRoute" @navigate="sidebarOpen = false" />

      <div class="sidebar-user">
        <span class="user-avatar">{{ avatarLetter }}</span>
        <div class="user-meta">
          <div class="user-name">{{ auth.name }}</div>
          <div class="user-role">
            {{ auth.role === 'teacher' ? '教师' : '学生' }}<template v-if="auth.role === 'student' && auth.user?.student_no"> · {{ auth.user.student_no }}</template>
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
        :mode="railMode === 'calendar' ? 'calendar' : railMode === 'corrections' ? 'corrections' : 'notes'"
        @close="setRail(false)"
      />
    </aside>

    <!-- 右栏收起态入口（v0.8.2）：两场景各有专属按钮与类名，不再共用一个按钮换图标。
         提醒场景=信封形 notes-fab（未读角标读 student store，有未读时轻晃）；
         日历场景=日历形 cal-fab（中性色、无角标；v0.9.1 起订正日历场景共用此按钮）。
         层级见 style.css 的 z-index 梳理注释。 -->
    <button
      v-if="railMode === 'notes' && !railOpen"
      class="notes-fab"
      :class="{ 'has-unread': student.unreadCount > 0 }"
      title="打开提醒"
      @click="setRail(true)"
    >
      <AppIcon name="mail" :size="20" />
      <span v-if="student.unreadCount > 0" :key="student.unreadCount" class="notes-badge">{{ student.unreadCount }}</span>
    </button>
    <button
      v-else-if="(railMode === 'calendar' || railMode === 'corrections') && !railOpen"
      class="cal-fab"
      title="打开日历"
      @click="setRail(true)"
    >
      <AppIcon name="calendar" :size="20" />
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useStudentStore } from './stores/student'
import { useTeacherStore } from './stores/teacher'
import AppIcon from './components/icons/AppIcon.vue'
import type { IconName } from './components/icons/paths'
import BrandLogo from './components/BrandLogo.vue'
import RightRail from './components/RightRail.vue'
import SidebarSessions from './components/SidebarSessions.vue'

const auth = useAuthStore()
const student = useStudentStore()
const teacher = useTeacherStore()
const router = useRouter()
const route = useRoute()
const sidebarOpen = ref(false)

// ---------- 对话页路由判定（v0.6.2）：侧栏会话区仅在双端对话页出现 ----------
const isChatRoute = computed(
  () => route.path === '/student/chat' || route.path === '/teacher/chat'
)

// ---------- 左侧栏收起状态（v0.6.2，桌面端）：localStorage 记忆，首次默认展开 ----------
// 移动端沿用抽屉逻辑（sidebarOpen），不受此状态影响。
const SIDEBAR_KEY = 'remedi-sidebar-open'
function initSidebarCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === '0'
  } catch {
    return false
  }
}
const sidebarCollapsed = ref(initSidebarCollapsed())
function setSidebarCollapsed(collapsed: boolean) {
  sidebarCollapsed.value = collapsed
  try {
    localStorage.setItem(SIDEBAR_KEY, collapsed ? '0' : '1')
  } catch {
    /* 忽略写入失败 */
  }
}

interface NavItem {
  to: string
  icon: IconName
  label: string
  exact?: boolean
  badge?: number // v0.9.0：角标数（如教师「待审核」待审数），0/缺省不显示
}

const STUDENT_NAV: NavItem[] = [
  { to: '/student/chat', icon: 'chat', label: '智能批改' },
  { to: '/student/assignments', icon: 'clipboard', label: '作业列表' },
  { to: '/student/submit', icon: 'edit', label: '交作业' },
  { to: '/student/mistakes', icon: 'book', label: '错题本' },
  { to: '/student/report', icon: 'chart', label: '学习报告' },
  { to: '/student/corrections', icon: 'check', label: '订正错题' },
  { to: '/student/profile', icon: 'user', label: '我的档案' }
]

const TEACHER_NAV: NavItem[] = [
  // v0.6.0：AI 助手排第一位（教师登录默认落点仍为总览，不变）
  { to: '/teacher/chat', icon: 'sparkles', label: 'AI 助手' },
  { to: '/teacher/dashboard', icon: 'chart', label: '总览' },
  { to: '/teacher/submissions', icon: 'file', label: '批改' },
  // v0.9.0：AI 批改先过教师审核才发给学生；角标数在 navItems 里从 teacher store 注入
  { to: '/teacher/reviews', icon: 'check', label: '待审核' },
  { to: '/teacher/students', icon: 'users', label: '学生' },
  { to: '/teacher/assignments', icon: 'clipboard', label: '作业', exact: true },
  { to: '/teacher/assignments/new', icon: 'plus-circle', label: '发布作业' },
  { to: '/teacher/workbooks', icon: 'book', label: '我的练习' },
  { to: '/teacher/suggestions', icon: 'lightbulb', label: '教学建议' }
]

const navItems = computed<NavItem[]>(() => {
  if (auth.role !== 'teacher') return STUDENT_NAV
  return TEACHER_NAV.map((it) =>
    it.to === '/teacher/reviews' && teacher.pendingReviewCount > 0
      ? { ...it, badge: teacher.pendingReviewCount }
      : it
  )
})
const avatarLetter = computed(() => (auth.name ? auth.name.slice(0, 1) : 'R'))

// ---------- 右侧栏场景（v0.3.1）：按角色 + 当前路由决定 ----------
// 学生：作业列表页放作业日历；订正页放订正日历（v0.9.1）；其余页面（含主页对话页）
// 只放便利贴提醒。教师：仅作业管理页放日历；其余页面不挂右栏（教师无通知）。
type RailMode = 'notes' | 'calendar' | 'corrections' | 'none'
const railMode = computed<RailMode>(() => {
  if (auth.role === 'teacher') {
    return route.path === '/teacher/assignments' ? 'calendar' : 'none'
  }
  if (route.path === '/student/assignments') return 'calendar'
  if (route.path === '/student/corrections') return 'corrections'
  return 'notes'
})

// ---------- 右侧栏展开状态（v0.8.2）：按场景分键存 localStorage，互不串扰 ----------
// notes 与 calendar 各记各的展开状态；切换场景（路由变化）时读入该场景的记忆值。
// 首次默认展开（窄屏默认收起）。旧的单键 remedi-rail-open 自 v0.8.2 起不再读写。
const RAIL_KEYS = {
  notes: 'remedi-rail-open-notes',
  calendar: 'remedi-rail-open-calendar',
  corrections: 'remedi-rail-open-corrections'
} as const
function railDefaultOpen(): boolean {
  return window.innerWidth >= 1200
}
function initRailFor(mode: 'notes' | 'calendar' | 'corrections'): boolean {
  try {
    const saved = localStorage.getItem(RAIL_KEYS[mode])
    if (saved === '1') return true
    if (saved === '0') return false
  } catch {
    /* localStorage 不可用时走默认 */
  }
  return railDefaultOpen()
}
const railOpen = ref(railDefaultOpen())
watch(railMode, (mode) => {
  if (mode !== 'none') railOpen.value = initRailFor(mode)
}, { immediate: true })

function setRail(open: boolean) {
  railOpen.value = open
  const mode = railMode.value
  if (mode === 'none') return
  try {
    localStorage.setItem(RAIL_KEYS[mode], open ? '1' : '0')
  } catch {
    /* 忽略写入失败 */
  }
}

// ---------- 未读数 / 待审计数刷新（v0.8.2 / v0.9.0）：进入对应角色任何页面（路由变化）时刷新一次 ----------
// 未读数由 student store 持有，RightRail 读/写后同步回写，FAB 角标直接读 store；
// 待审核数由 teacher store 持有，教师导航「待审核」角标直接读 store。
watch(
  () => route.path,
  () => {
    if (auth.role === 'student') void student.refreshUnread()
    if (auth.role === 'teacher') void teacher.refreshPendingReviewCount()
  },
  { immediate: true }
)

function logout() {
  // 退出时清掉双端的日历日期筛选与会话区状态，避免换人登录后残留旧状态
  useStudentStore().setAssignmentDateFilter('')
  useStudentStore().setCorrectionsDateFilter('')
  useTeacherStore().setAssignmentDateFilter('')
  useStudentStore().clearSessionState()
  useTeacherStore().clearSessionState()
  // v0.8.2：重置右栏展开态（回默认并清掉分键记忆）与未读数，避免换人登录后残留
  railOpen.value = railDefaultOpen()
  try {
    localStorage.removeItem(RAIL_KEYS.notes)
    localStorage.removeItem(RAIL_KEYS.calendar)
    localStorage.removeItem(RAIL_KEYS.corrections)
  } catch {
    /* 忽略清理失败 */
  }
  student.resetUnread()
  // v0.9.0：待审核角标一并清掉，避免换人登录后残留上一位老师的数字
  teacher.pendingReviews = []
  teacher.pendingReviewCount = 0
  auth.logout()
  router.push('/')
}
</script>
