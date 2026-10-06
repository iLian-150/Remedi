import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '../stores/auth'

// 角色选择 + 登录
import RoleSelect from '../views/RoleSelect.vue'
// 学生端
import StudentChat from '../views/student/StudentChat.vue'
import StudentAssignments from '../views/student/StudentAssignments.vue'
import StudentSubmit from '../views/student/StudentSubmit.vue'
import StudentFeedback from '../views/student/StudentFeedback.vue'
import StudentReport from '../views/student/StudentReport.vue'
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

const routes: RouteRecordRaw[] = [
  { path: '/', component: RoleSelect, meta: { public: true, title: '登录' } },

  // 学生端（登录默认落地页为对话式智能批改）
  { path: '/student/chat', component: StudentChat, meta: { role: 'student', title: '智能批改' } },
  { path: '/student/assignments', component: StudentAssignments, meta: { role: 'student', title: '作业列表' } },
  // 交作业：从作业列表进入（?assignment_id=），直接访问 URL 时回退为下拉选择
  { path: '/student/submit', component: StudentSubmit, meta: { role: 'student', title: '交作业' } },
  { path: '/student/feedback', component: StudentFeedback, meta: { role: 'student', title: '诊断报告' } },
  { path: '/student/report', component: StudentReport, meta: { role: 'student', title: '学习报告' } },
  { path: '/student/profile', component: StudentProfile, meta: { role: 'student', title: '我的档案' } },
  { path: '/student/corrections', component: StudentCorrections, meta: { role: 'student', title: '订正错题' } },

  // 教师端（诊断详情 :id 为 error_id，契约 4.1 未提供单条查询，用列表定位）
  { path: '/teacher/dashboard', component: TeacherDashboard, meta: { role: 'teacher', title: '班级总览' } },
  { path: '/teacher/submissions', component: TeacherSubmissions, meta: { role: 'teacher', title: '批改纠错' } },
  { path: '/teacher/submissions/:id', component: TeacherSubmissionDetail, meta: { role: 'teacher', title: '诊断详情' } },
  { path: '/teacher/students', component: TeacherStudents, meta: { role: 'teacher', title: '学生列表' } },
  { path: '/teacher/students/:id', component: TeacherStudentPortrait, meta: { role: 'teacher', title: '学生画像' } },
  { path: '/teacher/suggestions', component: TeacherSuggestions, meta: { role: 'teacher', title: '教学建议' } },
  { path: '/teacher/assignments', component: TeacherAssignments, meta: { role: 'teacher', title: '作业管理' } },
  { path: '/teacher/assignments/new', component: TeacherPublish, meta: { role: 'teacher', title: '发布作业' } }
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
