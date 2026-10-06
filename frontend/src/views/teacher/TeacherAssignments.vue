<!-- 教师端：作业管理（v0.2.0 新增）
     数据源：GET /api/teacher/assignments（4.8），含每题提交人数。
     v0.2.1：顶部加作业日历（按发布日期标记），点某天在下方列出当天发布的作业（含提交数）。 -->
<template>
  <div class="page">
    <div class="page-head" style="display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap">
      <div>
        <h2>作业管理</h2>
        <p class="page-sub">已发布的作业与每道题的提交情况。</p>
      </div>
      <router-link to="/teacher/assignments/new"><button class="btn inline-icon"><AppIcon name="plus" :size="16" /> 发布新作业</button></router-link>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">作业加载中…</div>

    <template v-if="!loading">
      <!-- 作业日历 -->
      <div class="card">
        <h3><AppIcon name="clipboard" :size="18" /> 作业日历</h3>
        <p class="card-sub">带圆点的是有作业发布的日子，点一天查看当天发布的作业。</p>
        <AssignmentCalendar :marks="calMarks" :selected="selectedDate" @select="selectedDate = $event" />
        <div class="day-list">
          <p class="day-title">{{ selectedDate }} 发布的作业</p>
          <div v-if="!dayAssignments.length" class="empty" style="padding: 18px 0">这一天没有发布作业。</div>
          <div v-for="a in dayAssignments" :key="a.id" class="day-row">
            <div class="day-main">
              <p class="day-name">{{ a.title }}</p>
              <p class="day-meta">
                <span class="badge badge-blue">{{ subjectLabel(a) }}</span>
                <span>{{ fmtTime(a.created_at) }} 发布</span>
                <span class="tnum">共 {{ a.questions.length }} 题</span>
                <span class="tnum">累计提交 {{ totalSubmissions(a) }} 人次</span>
              </p>
            </div>
          </div>
        </div>
      </div>

      <!-- 全部作业 -->
      <div v-for="a in assignments" :key="a.id" class="card">
        <h3>{{ a.title }}</h3>
        <p class="card-sub">{{ fmtTime(a.created_at) }} 发布 · 共 {{ a.questions.length }} 题</p>
        <table class="table">
          <thead>
            <tr><th style="width: 72px">题型</th><th>题干</th><th style="width: 130px">知识点</th><th style="width: 96px">已提交</th></tr>
          </thead>
          <tbody>
            <tr v-for="q in a.questions" :key="q.id">
              <td>
                <span v-if="q.type === 'math'" class="badge badge-blue">数学</span>
                <span v-else class="badge badge-gray">其他题型</span>
              </td>
              <td>{{ q.prompt }}</td>
              <td>{{ q.knowledge_point }}</td>
              <td class="num tnum">{{ q.submission_count }} 人</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="!assignments.length" class="card">
        <div class="empty">还没有发布过作业，点右上角「发布新作业」开始布置吧。</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useTeacherStore } from '../../stores/teacher'
import type { TeacherAssignment } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'
import AssignmentCalendar from '../../components/AssignmentCalendar.vue'

const teacher = useTeacherStore()
const assignments = ref<TeacherAssignment[]>([])
const loading = ref(false)
const error = ref('')

const todayKey = (() => {
  const d = new Date()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
})()
const selectedDate = ref(todayKey)

function dateOf(iso: string): string {
  return iso.slice(0, 10)
}
function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

const calMarks = computed<Record<string, number>>(() => {
  const marks: Record<string, number> = {}
  assignments.value.forEach((a) => {
    const d = dateOf(a.created_at)
    marks[d] = (marks[d] ?? 0) + 1
  })
  return marks
})

const dayAssignments = computed(() =>
  assignments.value.filter((a) => dateOf(a.created_at) === selectedDate.value)
)

function subjectLabel(a: TeacherAssignment): string {
  const types = [...new Set(a.questions.map((q) => q.type))]
  if (!types.length) return '数学'
  return types.map((t) => (t === 'math' ? '数学' : '其他题型')).join(' · ')
}

function totalSubmissions(a: TeacherAssignment): number {
  return a.questions.reduce((sum, q) => sum + q.submission_count, 0)
}

onMounted(async () => {
  loading.value = true
  try {
    assignments.value = await teacher.fetchTeacherAssignments()
    if (assignments.value.length) {
      const latest = [...assignments.value].sort((x, y) => (x.created_at < y.created_at ? 1 : -1))[0]
      selectedDate.value = dateOf(latest.created_at)
    }
  } catch (e) {
    error.value = '作业列表加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.day-list { margin-top: 18px; border-top: 1px solid #F1F3F6; padding-top: 14px; }
.day-title { font-size: 14.5px; font-weight: 700; margin-bottom: 8px; }
.day-row {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 4px; border-bottom: 1px solid #F1F3F6;
}
.day-row:last-child { border-bottom: none; }
.day-main { flex: 1; min-width: 0; }
.day-name { font-size: 14.5px; font-weight: 600; }
.day-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12.5px; color: var(--text-2); margin-top: 3px; }
</style>
