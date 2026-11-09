<template>
  <div class="page">
    <div class="page-head analytics-head">
      <div>
        <h2>作业学情</h2>
        <p v-if="report" class="page-sub">{{ report.title }}</p>
      </div>
      <div class="head-actions">
        <router-link class="btn small secondary" to="/teacher/assignments">返回作业</router-link>
        <router-link v-if="assignmentId" class="btn small secondary" :to="`/teacher/assignments/${assignmentId}`">查看题目</router-link>
      </div>
    </div>

    <div v-if="loading" class="loading">学情加载中…</div>
    <div v-else-if="error" class="error-msg">{{ error }}</div>

    <template v-else-if="report">
      <div class="stat-row kpi-row">
        <div class="stat"><div class="stat-num tnum">{{ report.student_count }}</div><div class="stat-label">接收学生</div></div>
        <div class="stat blue-stat"><div class="stat-num tnum">{{ report.started_count }}</div><div class="stat-label">已开始</div></div>
        <div class="stat green"><div class="stat-num tnum">{{ report.completed_count }}</div><div class="stat-label">已交齐</div></div>
        <div class="stat amber"><div class="stat-num tnum">{{ report.grading_count }}</div><div class="stat-label">待批改题数</div></div>
        <div class="stat amber"><div class="stat-num tnum">{{ report.review_count }}</div><div class="stat-label">待教师复核</div></div>
      </div>

      <div class="analytics-grid">
        <section class="card">
          <h3>学生完成情况</h3>
          <AsyncEChartPie v-if="report.student_count" :option="progressOption" />
          <div v-else class="empty">暂无接收学生。</div>
        </section>

        <section class="card">
          <h3>各题平均得分率</h3>
          <AsyncEChartBar
            v-if="report.questions.length"
            :option="questionOption"
            :style="{ height: questionChartHeight }"
          />
          <div v-else class="empty">暂无可查看的题目。</div>
        </section>
      </div>

      <section class="card student-card">
        <h3>学生作答情况 <span class="section-count">{{ report.students.length }} 人</span></h3>
        <div v-if="report.students.length" class="student-table-wrap">
          <table class="table student-table">
            <thead>
              <tr>
                <th>学生</th>
                <th>提交进度</th>
                <th>已批改</th>
                <th>当前得分</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="student in report.students" :key="student.id">
                <td>
                  <span class="student-name">{{ student.name }}</span>
                  <span v-if="student.student_no" class="student-no tnum">{{ student.student_no }}</span>
                </td>
                <td class="tnum">{{ student.submitted_questions }} / {{ student.expected_questions }} 题</td>
                <td class="tnum">{{ student.graded_questions }} 题</td>
                <td class="tnum">
                  <template v-if="student.max_score">{{ student.score }} / {{ student.max_score }}（{{ percent(student.score_rate) }}）</template>
                  <span v-else class="muted">—</span>
                </td>
                <td><span class="badge" :class="statusClass(student.status)">{{ student.status }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty">暂无接收学生。</div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import type { TeacherAssignmentAnalytics } from '../../api/types'
import { AsyncEChartBar, AsyncEChartPie } from '../../components/AsyncEChart'
import { useTeacherStore } from '../../stores/teacher'
import { getSubjectLabel } from '../../utils/subjectLabels'
import { readChartColors } from '../../utils/chartTheme'

const route = useRoute()
const teacher = useTeacherStore()
const report = ref<TeacherAssignmentAnalytics | null>(null)
const loading = ref(false)
const error = ref('')
const chartColors = readChartColors()
const assignmentId = computed(() => {
  const value = Number(route.params.id)
  return Number.isInteger(value) && value > 0 ? value : null
})

watch(assignmentId, (id) => { void load(id) }, { immediate: true })

let loadGeneration = 0

async function load(id: number | null) {
  const generation = ++loadGeneration
  report.value = null
  error.value = ''
  if (!id) {
    error.value = '作业编号无效。'
    loading.value = false
    return
  }
  loading.value = true
  try {
    const result = await teacher.fetchTeacherAssignmentAnalytics(id)
    if (generation === loadGeneration) report.value = result
  } catch {
    if (generation === loadGeneration) error.value = '学情加载失败，请稍后重试。'
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

const progressLabels = ['未开始', '部分提交', '截止后批改', '批改中', '待复核', '已完成'] as const
const progressOption = computed(() => {
  const data = progressLabels
    .map((name) => ({ name, value: report.value?.progress_counts[name] ?? 0 }))
    .filter((item) => item.value > 0)
  return {
    color: [chartColors.gray, chartColors.amber, chartColors.textStrong, chartColors.primary, chartColors.amber, chartColors.green],
    tooltip: { trigger: 'item', formatter: (item: { name: string; value: number; percent: number }) => `${item.name}：${item.value} 人（${item.percent}%）` },
    legend: { bottom: 0, textStyle: { color: chartColors.textMuted } },
    series: [{
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['50%', '46%'],
      data,
      label: { formatter: '{b}\n{c} 人', color: chartColors.textStrong },
      itemStyle: { borderColor: chartColors.surface, borderWidth: 2 }
    }]
  }
})

const questionChartHeight = computed(() => {
  const count = report.value?.questions.length ?? 0
  return `${Math.max(300, Math.min(720, count * 42 + 72))}px`
})

const questionOption = computed(() => {
  const questions = report.value?.questions ?? []
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ dataIndex: number; value: number | null }>) => {
        const question = questions[params[0]?.dataIndex]
        if (!question) return ''
        const rate = question.average_score_rate
        const scoreText = rate === null ? '尚无批改结果' : `平均得分率 ${Math.round(rate * 100)}%`
        return `第 ${question.number} 题 · ${subjectLabel(question.subject)} · ${escapeTooltip(question.knowledge_point || '待归类')}<br/>${escapeTooltip(question.prompt)}<br/>${scoreText}<br/>已提交 ${question.submitted_students} / ${question.expected_students} 人 · 已批改 ${question.graded_students} 人`
      }
    },
    grid: { left: 20, right: 28, top: 16, bottom: 16, containLabel: true },
    xAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { formatter: (value: number) => `${value}%`, color: chartColors.textMuted },
      splitLine: { lineStyle: { color: chartColors.border } }
    },
    yAxis: {
      type: 'category',
      data: questions.map((question) => `第 ${question.number} 题 · ${subjectLabel(question.subject)} · ${question.knowledge_point || '待归类'}`),
      axisLabel: { width: 190, overflow: 'truncate', color: chartColors.textStrong }
    },
    series: [{
      type: 'bar',
      data: questions.map((question) => question.average_score_rate === null ? null : Math.round(question.average_score_rate * 100)),
      itemStyle: { color: chartColors.primary, borderRadius: [0, 6, 6, 0] },
      barMaxWidth: 26,
      label: { show: true, position: 'right', formatter: (item: { value: number | null }) => item.value === null ? '' : `${item.value}%`, color: chartColors.textMuted }
    }]
  }
})

function percent(rate: number | null): string {
  return rate === null ? '—' : `${Math.round(rate * 100)}%`
}

const subjectLabel = (subject: string) => getSubjectLabel(subject)

function statusClass(status: string): string {
  if (status === '已完成') return 'badge-green'
  if (status === '批改中') return 'badge-blue'
  if (status === '截止后批改') return 'badge-gray'
  if (status === '部分提交' || status === '待复核') return 'badge-amber'
  return 'badge-gray'
}

const escapeEntities: Record<string, string> = {
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}

function escapeTooltip(value: string): string {
  return value.replace(/[&<>"']/g, (char) => escapeEntities[char] ?? char)
}
</script>

<style scoped>
.analytics-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.head-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.kpi-row { margin-bottom: 16px; }
.blue-stat .stat-num { color: var(--primary); }
.analytics-grid { display: grid; grid-template-columns: minmax(280px, 0.8fr) minmax(0, 1.2fr); gap: 16px; align-items: start; }
.analytics-grid .card { min-width: 0; }
.student-card { margin-top: 16px; }
.section-count { margin-left: auto; color: var(--text-3); font-size: 13px; font-weight: 500; }
.student-table-wrap { max-height: 560px; overflow: auto; }
.student-table thead { position: sticky; top: 0; z-index: 1; }
.student-name { font-weight: 600; }
.student-no { display: inline-block; margin-left: 8px; color: var(--text-3); font-size: 12px; }
.muted { color: var(--text-3); }
@media (max-width: 820px) {
  .analytics-grid { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 600px) {
  .analytics-head { flex-direction: column; }
  .student-table { min-width: 650px; }
}
</style>
