import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes: RouteRecordRaw[] = [
  { path: '/', component: () => import('../views/RoleSelect.vue'), meta: { public: true, title: '登录' } },

  // 学生端（登录默认落地页为对话式智能批改）
  { path: '/student/chat', component: () => import('../views/student/StudentChat.vue'), meta: { role: 'student', title: '智能批改' } },
  { path: '/student/assignments', component: () => import('../views/student/StudentAssignments.vue'), meta: { role: 'student', title: '作业列表' } },
  // 交作业：从作业列表进入（?assignment_id=），直接访问 URL 时回退为下拉选择
  { path: '/student/submit', component: () => import('../views/student/StudentSubmit.vue'), meta: { role: 'student', title: '交作业' } },
  // 错题本 canonical 路径（v0.8.2 正名，原 /student/feedback）
  { path: '/student/mistakes', component: () => import('../views/student/StudentMistakeNotebook.vue'), meta: { role: 'student', title: '错题本' } },
  { path: '/student/diagnosis', component: () => import('../views/student/StudentDiagnosis.vue'), meta: { role: 'student', title: '诊断详情' } },
  // 旧路径兼容（v0.8.2）：/student/feedback 曾同时指错题本与诊断，历史通知/外链可能还带它，
  // 统一重定向到诊断页（带 submission_id 的旧链接语义正是诊断详情）
  { path: '/student/feedback', redirect: '/student/diagnosis' },
  { path: '/student/report', component: () => import('../views/student/StudentReport.vue'), meta: { role: 'student', title: '学习报告' } },
  // 学习报告科目详情（v0.6.0 从报告页拆出独立页，带返回键；?verify= 深链打开验证面板）
  { path: '/student/report/:subject', component: () => import('../views/student/StudentReportSubject.vue'), meta: { role: 'student', title: '学习报告' } },
  { path: '/student/profile', component: () => import('../views/student/StudentProfile.vue'), meta: { role: 'student', title: '我的档案' } },
  { path: '/student/corrections', component: () => import('../views/student/StudentCorrections.vue'), meta: { role: 'student', title: '订正错题' } },

  // 教师端（诊断详情 :id 为 error_id，契约 4.1 未提供单条查询，用列表定位）
  { path: '/teacher/dashboard', component: () => import('../views/teacher/TeacherDashboard.vue'), meta: { role: 'teacher', title: '班级总览' } },
  { path: '/teacher/submissions', component: () => import('../views/teacher/TeacherSubmissions.vue'), meta: { role: 'teacher', title: '批改纠错' } },
  // 待审核（v0.9.0）：AI 批改先过教师审核才发给学生；?submission_id= 可直达某份
  { path: '/teacher/reviews', component: () => import('../views/teacher/TeacherReviews.vue'), meta: { role: 'teacher', title: '待审核' } },
  { path: '/teacher/submissions/:id', component: () => import('../views/teacher/TeacherSubmissionDetail.vue'), meta: { role: 'teacher', title: '诊断详情' } },
  { path: '/teacher/students', component: () => import('../views/teacher/TeacherStudents.vue'), meta: { role: 'teacher', title: '学生列表' } },
  { path: '/teacher/students/:id', component: () => import('../views/teacher/TeacherStudentPortrait.vue'), meta: { role: 'teacher', title: '学生画像' } },
  { path: '/teacher/suggestions', component: () => import('../views/teacher/TeacherSuggestions.vue'), meta: { role: 'teacher', title: '教学建议' } },
  { path: '/teacher/assignments', component: () => import('../views/teacher/TeacherAssignments.vue'), meta: { role: 'teacher', title: '作业管理' } },
  { path: '/teacher/assignments/new', component: () => import('../views/teacher/TeacherPublish.vue'), meta: { role: 'teacher', title: '发布作业' } },
  { path: '/teacher/chat', component: () => import('../views/teacher/TeacherChat.vue'), meta: { role: 'teacher', title: 'AI 助手' } },
  { path: '/teacher/agents', component: () => import('../views/teacher/TeacherKnowledge.vue'), meta: { role: 'teacher', title: '学科 Agent 知识库' } },
  // 我的练习（v0.6.0）：练习册知识库的书架式管理页，与 4.15~4.17 同一批接口
  { path: '/teacher/workbooks', component: () => import('../views/teacher/TeacherWorkbooks.vue'), meta: { role: 'teacher', title: '我的练习' } }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  // v0.13.6：换页恒回顶部——此前没配 scrollBehavior，从长页面点进发布页会停在原来的
  // 滚动位置上，顶部标题看起来「变了位置」；回顶部后每次进来位置都一致。
  // 但同页内的 query 变化（如发布页选模式时 replace ?mode=）不许动滚动位置，
  // 否则点一下模式卡标题又会跳——按 path 是否变化区分这两种情况。
  scrollBehavior: (to, from) => (to.path === from.path ? false : { top: 0 })
})

// 路由守卫：未登录强制回登录页；角色不匹配时跳到各自首页
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.public) {
    if (!auth.token) return true
    return auth.role === 'teacher' ? '/teacher/dashboard' : '/student/chat'
  }
  if (!auth.token) return '/'
  if (to.meta.role && to.meta.role !== auth.role) {
    return auth.role === 'teacher' ? '/teacher/dashboard' : '/student/chat'
  }
  return true
})

export default router
