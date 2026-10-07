import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '../stores/auth'

// 角色选择 + 登录
import RoleSelect from '../views/RoleSelect.vue'
// 学生端
import StudentChat from '../views/student/StudentChat.vue'
import StudentAssignments from '../views/student/StudentAssignments.vue'
import StudentSubmit from '../views/student/StudentSubmit.vue'
import StudentDiagnosis from '../views/student/StudentDiagnosis.vue'
import StudentMistakeNotebook from '../views/student/StudentMistakeNotebook.vue'
import StudentReport from '../views/student/StudentReport.vue'
import StudentReportSubject from '../views/student/StudentReportSubject.vue'
import StudentProfile from '../views/student/StudentProfile.vue'
import StudentCorrections from '../views/student/StudentCorrections.vue'
// 教师端
import TeacherDashboard from '../views/teacher/TeacherDashboard.vue'
import TeacherSubmissions from '../views/teacher/TeacherSubmissions.vue'
import TeacherSubmissionDetail from '../views/teacher/TeacherSubmissionDetail.vue'
import TeacherStudents from '../views/teacher/TeacherStudents.vue'
import TeacherStudentPortrait from '../views/teacher/TeacherStudentPortrait.vue'
import TeacherSuggestions from '../views/teacher/TeacherSuggestions.vue'
import TeacherAssignments from '../views/teacher/TeacherAssignments.vue'
import TeacherPublish from '../views/teacher/TeacherPublish.vue'
import TeacherChat from '../views/teacher/TeacherChat.vue'
import TeacherWorkbooks from '../views/teacher/TeacherWorkbooks.vue'
import TeacherReviews from '../views/teacher/TeacherReviews.vue'

const routes: RouteRecordRaw[] = [
  { path: '/', component: RoleSelect, meta: { public: true, title: '登录' } },

  // 学生端（登录默认落地页为对话式智能批改）
  { path: '/student/chat', component: StudentChat, meta: { role: 'student', title: '智能批改' } },
  { path: '/student/assignments', component: StudentAssignments, meta: { role: 'student', title: '作业列表' } },
  // 交作业：从作业列表进入（?assignment_id=），直接访问 URL 时回退为下拉选择
  { path: '/student/submit', component: StudentSubmit, meta: { role: 'student', title: '交作业' } },
  // 错题本 canonical 路径（v0.8.2 正名，原 /student/feedback）
  { path: '/student/mistakes', component: StudentMistakeNotebook, meta: { role: 'student', title: '错题本' } },
  { path: '/student/diagnosis', component: StudentDiagnosis, meta: { role: 'student', title: '诊断详情' } },
  // 旧路径兼容（v0.8.2）：/student/feedback 曾同时指错题本与诊断，历史通知/外链可能还带它，
  // 统一重定向到诊断页（带 submission_id 的旧链接语义正是诊断详情）
  { path: '/student/feedback', redirect: '/student/diagnosis' },
  { path: '/student/report', component: StudentReport, meta: { role: 'student', title: '学习报告' } },
  // 学习报告科目详情（v0.6.0 从报告页拆出独立页，带返回键；?verify= 深链打开验证面板）
  { path: '/student/report/:subject', component: StudentReportSubject, meta: { role: 'student', title: '学习报告' } },
  { path: '/student/profile', component: StudentProfile, meta: { role: 'student', title: '我的档案' } },
  { path: '/student/corrections', component: StudentCorrections, meta: { role: 'student', title: '订正错题' } },

  // 教师端（诊断详情 :id 为 error_id，契约 4.1 未提供单条查询，用列表定位）
  { path: '/teacher/dashboard', component: TeacherDashboard, meta: { role: 'teacher', title: '班级总览' } },
  { path: '/teacher/submissions', component: TeacherSubmissions, meta: { role: 'teacher', title: '批改纠错' } },
  // 待审核（v0.9.0）：AI 批改先过教师审核才发给学生；?submission_id= 可直达某份
  { path: '/teacher/reviews', component: TeacherReviews, meta: { role: 'teacher', title: '待审核' } },
  { path: '/teacher/submissions/:id', component: TeacherSubmissionDetail, meta: { role: 'teacher', title: '诊断详情' } },
  { path: '/teacher/students', component: TeacherStudents, meta: { role: 'teacher', title: '学生列表' } },
  { path: '/teacher/students/:id', component: TeacherStudentPortrait, meta: { role: 'teacher', title: '学生画像' } },
  { path: '/teacher/suggestions', component: TeacherSuggestions, meta: { role: 'teacher', title: '教学建议' } },
  { path: '/teacher/assignments', component: TeacherAssignments, meta: { role: 'teacher', title: '作业管理' } },
  { path: '/teacher/assignments/new', component: TeacherPublish, meta: { role: 'teacher', title: '发布作业' } },
  { path: '/teacher/chat', component: TeacherChat, meta: { role: 'teacher', title: 'AI 助手' } },
  // 我的练习（v0.6.0）：练习册知识库的书架式管理页，与 4.15~4.17 同一批接口
  { path: '/teacher/workbooks', component: TeacherWorkbooks, meta: { role: 'teacher', title: '我的练习' } }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 路由守卫：未登录强制回登录页；角色不匹配时跳到各自首页
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.public) return true
  if (!auth.token) return '/'
  if (to.meta.role && to.meta.role !== auth.role) {
    return auth.role === 'teacher' ? '/teacher/dashboard' : '/student/chat'
  }
  return true
})

export default router
