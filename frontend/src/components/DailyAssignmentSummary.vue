<template>
  <section class="card daily-summary" aria-labelledby="daily-summary-title">
    <header class="summary-header">
      <div class="summary-title">
        <span class="summary-title-icon"><AppIcon name="chart" :size="17" /></span>
        <h2 id="daily-summary-title">今日作业</h2>
      </div>
      <time class="summary-date" :datetime="dayKey">{{ dateLabel }}</time>
    </header>

    <div class="metric-grid" :aria-busy="loading">
      <article class="metric metric-submission">
        <div class="metric-label">作业提交率</div>
        <div class="metric-value">{{ submissionLabel }}</div>
        <div class="metric-track" role="progressbar" aria-label="作业提交率" :aria-valuenow="submissionRate ?? undefined" aria-valuemin="0" aria-valuemax="100">
          <span :style="{ width: `${submissionRate ?? 0}%` }" />
        </div>
        <div class="metric-caption">已交 {{ totals.submitted }} / 应交 {{ totals.expected }} 人次</div>
      </article>

      <article class="metric metric-accuracy">
        <div class="metric-label">作业正确率</div>
        <div class="metric-value">{{ accuracyLabel }}</div>
        <div class="metric-track" role="progressbar" aria-label="作业正确率" :aria-valuenow="accuracyRate ?? undefined" aria-valuemin="0" aria-valuemax="100">
          <span :style="{ width: `${accuracyRate ?? 0}%` }" />
        </div>
        <div class="metric-caption">{{ accuracyRate === null ? '完成批改后显示' : `已批改 ${totals.graded} 人次` }}</div>
      </article>
    </div>

    <p v-if="loading" class="summary-status" role="status">正在汇总今日作业…</p>
    <p v-else-if="error" class="summary-status summary-error" role="alert">
      {{ error }}
      <button type="button" class="retry-button" @click="loadSummary">重试</button>
    </p>
    <p v-else-if="totals.assignments === 0" class="summary-status">今天还没有发布作业</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppIcon from './icons/AppIcon.vue'
import { useTeacherStore } from '../stores/teacher'

const teacher = useTeacherStore()
const today = ref(new Date())
const loading = ref(true)
const error = ref('')
const totals = ref({ assignments: 0, submitted: 0, expected: 0, earned: 0, possible: 0, graded: 0 })
const dayKey = computed(() => {
  const date = today.value
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
})
const dateLabel = computed(() => new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric', month: 'long', day: 'numeric', weekday: 'long'
}).format(today.value))
const submissionRate = computed(() => totals.value.expected
  ? Math.round(totals.value.submitted / totals.value.expected * 100)
  : null)
const accuracyRate = computed(() => totals.value.possible
  ? Math.round(totals.value.earned / totals.value.possible * 100)
  : null)
const submissionLabel = computed(() => loading.value || submissionRate.value === null
  ? '—' : `${submissionRate.value}%`)
const accuracyLabel = computed(() => loading.value
  ? '—' : accuracyRate.value === null ? '待批改' : `${accuracyRate.value}%`)

let requestGeneration = 0
let dateTimer: number | undefined

async function loadSummary() {
  const generation = ++requestGeneration
  const requestedDay = dayKey.value
  loading.value = true
  error.value = ''
  totals.value = { assignments: 0, submitted: 0, expected: 0, earned: 0, possible: 0, graded: 0 }
  try {
    const assignments = await teacher.fetchTeacherAssignments(requestedDay)
    const analytics = await Promise.all(assignments.map((assignment) =>
      teacher.fetchTeacherAssignmentAnalytics(assignment.id)
    ))
    if (generation !== requestGeneration) return

    totals.value = analytics.reduce((total, report) => {
      const gradedStudents = report.students.filter((student) => student.max_score > 0)
      total.assignments += 1
      total.submitted += report.completed_count
      total.expected += report.student_count
      total.earned += gradedStudents.reduce((sum, student) => sum + student.score, 0)
      total.possible += gradedStudents.reduce((sum, student) => sum + student.max_score, 0)
      total.graded += gradedStudents.length
      return total
    }, { assignments: 0, submitted: 0, expected: 0, earned: 0, possible: 0, graded: 0 })
  } catch (cause) {
    if (generation === requestGeneration) {
      error.value = '今日作业数据加载失败。'
      console.error(cause)
    }
  } finally {
    if (generation === requestGeneration) loading.value = false
  }
}

watch(dayKey, () => { void loadSummary() }, { immediate: true })
onMounted(() => {
  dateTimer = window.setInterval(() => { today.value = new Date() }, 60_000)
})
onBeforeUnmount(() => {
  requestGeneration += 1
  if (dateTimer !== undefined) window.clearInterval(dateTimer)
})
</script>

<style scoped>
.daily-summary { min-width: 0; margin-bottom: 0; padding: 20px; }
.summary-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 18px; }
.summary-title { display: flex; min-width: 0; align-items: center; gap: 9px; }
.summary-title h2 { color: var(--text); font-size: 16px; font-weight: 700; }
.summary-title-icon { display: grid; width: 34px; height: 34px; flex: 0 0 auto; place-items: center; border-radius: var(--radius-control); background: var(--primary-50); color: var(--primary); }
.summary-date { color: var(--text-2); font-size: 12px; font-variant-numeric: tabular-nums; text-align: right; }
.metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.metric { min-width: 0; padding: 14px; border: 1px solid var(--border); border-radius: var(--radius-control); background: var(--surface-2); }
.metric-label { color: var(--text-2); font-size: 13px; font-weight: 600; }
.metric-value { min-height: 43px; margin: 3px 0 8px; color: var(--text); font-size: clamp(24px, 2vw, 30px); font-variant-numeric: tabular-nums; font-weight: 750; letter-spacing: -0.04em; line-height: 1.35; }
.metric-accuracy .metric-value { font-size: clamp(21px, 1.75vw, 27px); letter-spacing: -0.025em; }
.metric-track { height: 6px; overflow: hidden; border-radius: var(--radius-pill); background: var(--border); }
.metric-track span { display: block; height: 100%; border-radius: inherit; background: var(--primary); transition: width .25s ease; }
.metric-accuracy .metric-track span { background: var(--green); }
.metric-caption { overflow: hidden; margin-top: 9px; color: var(--text-3); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.summary-status { margin-top: 14px; color: var(--text-2); font-size: 12px; }
.summary-error { color: var(--red-strong); }
.retry-button { margin-left: 8px; padding: 0; border: 0; background: transparent; color: var(--primary); cursor: pointer; font: inherit; font-weight: 650; }
.retry-button:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; border-radius: var(--radius-detail); }
@media (max-width: 560px) {
  .daily-summary { padding: 16px; }
  .metric-grid { grid-template-columns: minmax(0, 1fr); gap: 9px; }
  .metric { padding: 12px; }
  .metric-value { min-height: 0; margin-bottom: 6px; }
  .summary-header { align-items: flex-start; }
}
@media (prefers-reduced-motion: reduce) { .metric-track span { transition: none; } }
</style>
