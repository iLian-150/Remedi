<!-- 学生端：作业列表 —— 交作业的统一入口
     数据源：GET /api/student/assignments（契约 3.1）
     v0.2.1：顶部加作业日历（按发布日期标记），点某天在下方列出当天作业（含完成状态）。
     点击「开始作答」进入 /student/submit?assignment_id= -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>作业列表</h2>
      <p class="page-sub">选择一份作业开始作答，提交后会立即生成你的诊断报告。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">作业加载中…</div>

    <template v-if="!loading">
      <!-- 作业日历 -->
      <div class="card">
        <h3><AppIcon name="clipboard" :size="18" /> 作业日历</h3>
        <p class="card-sub">带圆点的是有作业发布的日子，点一天看看当天有哪些作业。</p>
        <AssignmentCalendar :marks="calMarks" :selected="selectedDate" @select="selectedDate = $event" />
        <div class="day-list">
          <p class="day-title">{{ selectedDate }} 的作业</p>
          <div v-if="!dayAssignments.length" class="empty" style="padding: 18px 0">这一天没有发布作业。</div>
          <div v-for="a in dayAssignments" :key="a.id" class="day-row">
            <div class="day-main">
              <p class="day-name">{{ a.title }}</p>
              <p class="day-meta">
                <span class="badge badge-blue">{{ subjectLabel(a) }}</span>
                <span>{{ fmtTime(a.created_at) }} 发布</span>
                <span class="tnum">{{ a.question_count }} 道题</span>
                <span :class="`badge ${statusBadge(a)}`">{{ statusText(a) }}</span>
              </p>
            </div>
            <router-link :to="`/student/submit?assignment_id=${a.id}`">
              <button class="btn small">开始作答</button>
            </router-link>
          </div>
        </div>
      </div>

      <!-- 全部作业 -->
      <div v-if="assignments.length" class="assign-grid">
        <div v-for="a in assignments" :key="a.id" class="card assign-card">
          <h3>{{ a.title }}</h3>
          <p class="assign-desc">{{ a.description || '暂无说明' }}</p>
          <div class="assign-meta">
            <span class="badge badge-blue tnum">{{ a.question_count }} 道题</span>
            <span :class="`badge ${statusBadge(a)}`">{{ statusText(a) }}</span>
            <span class="assign-time">{{ fmtTime(a.created_at) }} 发布</span>
          </div>
          <router-link :to="`/student/submit?assignment_id=${a.id}`">
            <button class="btn" style="width: 100%">开始作答</button>
          </router-link>
        </div>
      </div>

      <div v-if="!assignments.length" class="card">
        <div class="empty">老师还没有布置作业，稍后再来看看吧。</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useStudentStore } from '../../stores/student'
import type { Assignment } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'
import AssignmentCalendar from '../../components/AssignmentCalendar.vue'

const student = useStudentStore()

const assignments = ref<Assignment[]>([])
const loading = ref(false)
const error = ref('')

/** 每份作业的题目 id 集合与科目集合（由作业详情拼装，供完成状态/科目展示） */
const questionIdsByAssignment = ref<Record<number, number[]>>({})
const subjectsByAssignment = ref<Record<number, string[]>>({})
const doneQids = ref<Set<number>>(new Set())

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

function doneCount(a: Assignment): number {
  const qids = questionIdsByAssignment.value[a.id] ?? []
  return qids.filter((id) => doneQids.value.has(id)).length
}

function statusText(a: Assignment): string {
  const total = a.question_count
  const done = doneCount(a)
  if (total > 0 && done >= total) return '已完成'
  if (done > 0) return `进行中 ${done}/${total}`
  return '未开始'
}
function statusBadge(a: Assignment): string {
  const total = a.question_count
  const done = doneCount(a)
  if (total > 0 && done >= total) return 'badge-green'
  if (done > 0) return 'badge-amber'
  return 'badge-gray'
}

const SUBJECT_TEXT: Record<string, string> = { math: '数学', english: '英语' }
function subjectLabel(a: Assignment): string {
  const subs = subjectsByAssignment.value[a.id] ?? []
  if (!subs.length) return '数学'
  return subs.map((s) => SUBJECT_TEXT[s] ?? s).join(' · ')
}

onMounted(async () => {
  loading.value = true
  try {
    const [list, subs] = await Promise.all([
      student.fetchAssignments(),
      student.fetchMySubmissions().catch(() => [])
    ])
    assignments.value = list
    subs.forEach((s) => doneQids.value.add(s.question_id))
    const details = await Promise.all(list.map((a) => student.fetchAssignmentDetail(a.id)))
    details.forEach((d) => {
      questionIdsByAssignment.value[d.id] = d.questions.map((q) => q.id)
      subjectsByAssignment.value[d.id] = [...new Set(d.questions.map((q) => q.subject))]
    })
    // 默认选中最近一次有作业发布的日期，方便一眼看到内容
    if (list.length) {
      const latest = [...list].sort((x, y) => (x.created_at < y.created_at ? 1 : -1))[0]
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
