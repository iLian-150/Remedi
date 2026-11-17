<template>
  <div class="page">
    <div class="page-head analytics-head">
      <router-link class="back-link" to="/teacher/assignments/manage"><AppIcon name="chevron-left" :size="16" /> 返回作业管理</router-link>
      <div class="head-actions">
        <router-link v-if="assignmentId" class="btn small secondary" :to="`/teacher/assignments/${assignmentId}`">查看题目</router-link>
        <button class="btn small secondary inline-icon" type="button" :disabled="loading" @click="refresh"><AppIcon name="refresh" :size="15" />{{ loading ? '刷新中…' : '刷新学情' }}</button>
      </div>
    </div>

    <div v-if="loading" class="loading">学情加载中…</div>
    <div v-else-if="error" class="card analytics-error">
      <p class="error-msg">{{ error }}</p>
      <button class="btn small secondary" type="button" @click="refresh">重试</button>
    </div>

    <template v-else-if="report">
      <div class="stat-row kpi-row">
        <div class="stat"><div class="stat-num tnum">{{ report.student_count }}</div><div class="stat-label">接收学生</div></div>
        <div class="stat blue-stat"><div class="stat-num tnum">{{ report.started_count }}</div><div class="stat-label">已开始</div></div>
        <div class="stat green"><div class="stat-num tnum">{{ report.completed_count }}</div><div class="stat-label">已提交全部题目</div></div>
        <div class="stat amber"><div class="stat-num tnum">{{ report.grading_count }}</div><div class="stat-label">待批改题数</div></div>
        <div class="stat amber"><div class="stat-num tnum">{{ report.review_count }}</div><div class="stat-label">待教师复核</div></div>
        <div class="stat purple-stat"><div class="stat-num tnum">{{ percent(report.average_score_rate) }}</div><div class="stat-label">已评分题平均得分率</div></div>
      </div>

      <div class="analytics-grid">
        <section class="card">
          <h3>学生完成情况</h3>
          <AsyncEChartPie v-if="report.student_count" :option="progressOption" />
          <div v-else class="empty">暂无接收学生。</div>
        </section>

        <section class="card">
          <h3>各题作答情况</h3>
          <AsyncEChartBar
            v-if="report.questions.length"
            :option="questionOption"
            :style="{ height: questionChartHeight }"
          />
          <div v-else class="empty">暂无可查看的题目。</div>
          <div v-if="report.questions.length" class="question-table-wrap">
            <table class="table question-table">
              <thead><tr><th>题目</th><th>平均得分率</th><th>提交人数</th><th>已评分</th></tr></thead>
              <tbody>
                <tr v-for="question in report.questions" :key="question.id">
                  <td><strong>第 {{ question.number }} 题</strong><small>{{ subjectLabel(question.subject) }} · {{ question.knowledge_point || '待归类' }}</small></td>
                  <td class="tnum">{{ percent(question.average_score_rate) }}</td>
                  <td class="tnum">{{ question.submitted_students }} / {{ question.expected_students }}</td>
                  <td class="tnum">{{ question.graded_students }} 人</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section class="card student-card">
        <div class="section-heading">
          <h3>学生作答情况</h3>
          <div class="student-tools">
            <label class="student-search"><span class="sr-only">搜索学生</span><input v-model="studentQuery" type="search" placeholder="搜索姓名或学号" /></label>
            <label class="student-status-filter"><span class="sr-only">筛选提交状态</span><select v-model="statusFilter"><option value="">全部状态</option><option v-for="status in progressLabels" :key="status" :value="status">{{ status }}</option></select></label>
            <label class="student-score-filter"><span class="sr-only">筛选得分区间</span><select v-model="scoreFilter"><option value="">全部得分</option><option value="90">90% 及以上</option><option value="80">80%–89%</option><option value="60">60%–79%</option><option value="below60">低于 60%</option><option value="ungraded">暂无评分</option></select></label>
            <span class="section-count">{{ filteredStudents.length }} / {{ report.students.length }} 人</span>
          </div>
        </div>
        <div v-if="report.students.length" class="student-table-wrap">
          <table class="table student-table">
            <thead>
              <tr>
                <th>学生</th>
                <th>提交进度</th>
                <th>当前得分</th>
                <th>状态</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="student in filteredStudents" :key="student.id">
              <tr>
                <td>
                  <span class="student-name">{{ student.name }}</span>
                  <span v-if="student.student_no" class="student-no tnum">{{ student.student_no }}</span>
                </td>
                <td class="tnum">{{ student.submitted_questions }} / {{ student.expected_questions }} 题</td>
                <td class="tnum">
                  <template v-if="student.graded_questions">
                    <strong>{{ formatScore(student.score) }} / {{ formatScore(student.max_score) }}</strong>
                    <small class="score-caption">已评分 {{ student.graded_questions }} 题 · 得分率 {{ percent(student.score_rate) }}</small>
                  </template>
                  <span v-else class="muted">暂无评分</span>
                </td>
                <td><span class="badge" :class="statusClass(student.status)">{{ student.status }}</span></td>
                <td><button class="student-detail-toggle" type="button" :aria-expanded="expandedStudentId === student.id" @click="toggleStudent(student.id)">{{ expandedStudentId === student.id ? '收起' : '逐题明细' }}</button></td>
              </tr>
              <tr v-if="expandedStudentId === student.id" class="student-detail-row">
                <td colspan="5">
                  <div class="student-question-results">
                    <div class="student-question-results-head"><strong>{{ student.name }} · 逐题情况</strong><span>{{ student.graded_questions }} / {{ student.expected_questions }} 题已评分</span></div>
                    <div v-for="result in student.question_results" :key="result.question_id" class="student-question-result">
                      <div class="student-question-info">
                        <strong>第 {{ questionById.get(result.question_id)?.number ?? '—' }} 题 · {{ subjectLabel(questionById.get(result.question_id)?.subject ?? '') }}</strong>
                        <span>{{ questionById.get(result.question_id)?.knowledge_point || '待归类' }}</span>
                        <p>{{ questionById.get(result.question_id)?.prompt || '题目内容不可用' }}</p>
                      </div>
                      <div class="student-question-score">
                        <strong>{{ result.score === null ? '—' : formatScore(result.score) }} / {{ formatScore(result.max_score) }}</strong>
                        <span>{{ result.score === null ? '尚无评分' : percent(result.score_rate) }}</span>
                      </div>
                      <span class="badge" :class="statusClass(result.status)">{{ result.status }}</span>
                      <time v-if="result.submitted_at" class="student-question-time">{{ formatSubmittedAt(result.submitted_at) }} 提交</time>
                    </div>
                  </div>
                </td>
              </tr>
              </template>
              <tr v-if="!filteredStudents.length"><td colspan="5" class="empty-row">没有符合条件的学生。</td></tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty">暂无接收学生。</div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import type { TeacherAssignmentAnalytics } from '../../api/types'
import { AsyncEChartBar, AsyncEChartPie } from '../../components/AsyncEChart'
import AppIcon from '../../components/icons/AppIcon.vue'
import { useTeacherStore } from '../../stores/teacher'
import { getSubjectLabel } from '../../utils/subjectLabels'
import { readChartColors } from '../../utils/chartTheme'

const route = useRoute()
const teacher = useTeacherStore()
const report = ref<TeacherAssignmentAnalytics | null>(null)
const loading = ref(false)
const error = ref('')
const studentQuery = ref('')
const statusFilter = ref('')
const scoreFilter = ref('')
const expandedStudentId = ref<number | null>(null)
const chartColors = readChartColors()
let loadGeneration = 0
const assignmentId = computed(() => {
  const value = Number(route.params.id)
  return Number.isInteger(value) && value > 0 ? value : null
})

watch(assignmentId, (id, previousId) => {
  if (id !== previousId) {
    studentQuery.value = ''
    statusFilter.value = ''
    scoreFilter.value = ''
    expandedStudentId.value = null
    teacher.setAssignmentAnalyticsPageTitle('')
  }
  void load(id)
}, { immediate: true })
onBeforeUnmount(() => {
  loadGeneration += 1
  teacher.setAssignmentAnalyticsPageTitle('')
})

const progressLabels = ['未开始', '部分提交', '批改中', '待复核', '截止后批改', '已完成'] as const
const filteredStudents = computed(() => {
  const query = studentQuery.value.trim().toLocaleLowerCase()
  return (report.value?.students ?? []).filter((student) => {
    const matchesQuery = !query || `${student.name} ${student.student_no ?? ''}`.toLocaleLowerCase().includes(query)
    const matchesStatus = !statusFilter.value || student.status === statusFilter.value
    const matchesScore = matchesScoreFilter(student)
    return matchesQuery && matchesStatus && matchesScore
  })
})
const questionById = computed(() => new Map((report.value?.questions ?? []).map((question) => [question.id, question])))

function refresh() {
  void load(assignmentId.value)
}

function matchesScoreFilter(student: TeacherAssignmentAnalytics['students'][number]): boolean {
  if (scoreFilter.value === 'ungraded') return student.graded_questions === 0 || student.score_rate === null
  if (student.graded_questions === 0 || student.score_rate === null) return !scoreFilter.value

  const scorePercentage = Math.round(student.score_rate * 100)
  switch (scoreFilter.value) {
    case '90': return scorePercentage >= 90
    case '80': return scorePercentage >= 80 && scorePercentage < 90
    case '60': return scorePercentage >= 60 && scorePercentage < 80
    case 'below60': return scorePercentage < 60
    default: return true
  }
}

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
    if (!result || !Array.isArray(result.questions) || !Array.isArray(result.students)) {
      throw new Error('学情接口未返回有效数据。')
    }
    if (generation === loadGeneration) {
      report.value = result
      teacher.setAssignmentAnalyticsPageTitle(result.title)
    }
  } catch {
    if (generation === loadGeneration) error.value = '学情加载失败，请稍后重试。'
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

const progressOption = computed(() => {
  const data = progressLabels
    .map((name) => ({ name, value: report.value?.progress_counts[name] ?? 0 }))
    .filter((item) => item.value > 0)
  return {
    color: [chartColors.gray, chartColors.amber, chartColors.primary, chartColors.amber, chartColors.textStrong, chartColors.green],
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
        return `第 ${question.number} 题 · ${subjectLabel(question.subject)} · ${escapeTooltip(question.knowledge_point || '待归类')}<br/>${escapeTooltip(question.prompt)}<br/>${scoreText}<br/>已提交 ${question.submitted_students} / ${question.expected_students} 人 · 已评分 ${question.graded_students} 人`
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
      itemStyle: { color: chartColors.primary, borderRadius: [0, chartColors.radiusDetail, chartColors.radiusDetail, 0] },
      barMaxWidth: 26,
      label: { show: true, position: 'right', formatter: (item: { value: number | null }) => item.value === null ? '' : `${item.value}%`, color: chartColors.textMuted }
    }]
  }
})

function percent(rate: number | null): string {
  return rate === null ? '—' : `${Math.round(rate * 100)}%`
}

function formatScore(score: number): string {
  return Number.isInteger(score) ? String(score) : score.toFixed(1).replace(/\.0$/, '')
}

function formatSubmittedAt(value: string): string {
  return value.replace('T', ' ').slice(0, 16)
}

function toggleStudent(id: number) {
  expandedStudentId.value = expandedStudentId.value === id ? null : id
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
.analytics-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.head-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.kpi-row { margin-bottom: 16px; }
.blue-stat .stat-num { color: var(--primary); }
.purple-stat .stat-num { color: var(--purple); }
.analytics-grid { display: grid; grid-template-columns: minmax(280px, 0.8fr) minmax(0, 1.2fr); gap: 16px; align-items: start; }
.analytics-grid .card { min-width: 0; }
.analytics-grid h3 { margin-bottom: 10px; }
.question-table-wrap { max-height: 330px; margin-top: 12px; overflow: auto; }
.question-table { min-width: 470px; }
.question-table td:first-child strong, .question-table td:first-child small { display: block; }
.question-table td:first-child small { margin-top: 2px; color: var(--text-3); font-size: 11px; }
.student-card { margin-top: 16px; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.section-heading h3 { margin: 0; }
.student-tools { display: flex; min-width: 0; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px; }
.student-tools input, .student-tools select { min-height: 36px; padding: 6px 10px; border: 1px solid var(--border); border-radius: var(--radius-standard); color: var(--text); background: var(--card); font-size: 12px; }
.student-search input { width: min(220px, 24vw); }
.section-count { color: var(--text-3); font-size: 12px; font-weight: 500; white-space: nowrap; }
.student-table-wrap { max-height: 560px; overflow: auto; }
.student-table thead { position: sticky; top: 0; z-index: 1; }
.student-table { min-width: 700px; }
.student-table td { vertical-align: middle; }
.student-name { font-weight: 600; }
.student-no { display: inline-block; margin-left: 8px; color: var(--text-3); font-size: 12px; }
.score-caption { display: block; margin-top: 2px; color: var(--text-3); font-size: 11px; }
.student-detail-toggle { padding: 5px 10px; border: 1px solid var(--border); border-radius: var(--radius-standard); color: var(--primary); background: var(--card); cursor: pointer; font-size: 12px; font-weight: 600; }
.student-detail-toggle:hover { border-color: var(--primary); background: var(--primary-50); }
.student-detail-row > td { padding: 0 !important; background: var(--surface-2); }
.student-question-results { padding: 14px 18px; }
.student-question-results-head { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 8px; font-size: 12px; }
.student-question-results-head span { color: var(--text-3); }
.student-question-result { display: grid; grid-template-columns: minmax(0, 1fr) auto auto auto; align-items: center; gap: 12px; padding: 10px 0; border-top: 1px solid var(--border); }
.student-question-info { min-width: 0; }
.student-question-info > strong, .student-question-info > span { display: inline-block; margin-right: 8px; }
.student-question-info > span { color: var(--text-3); font-size: 11px; }
.student-question-info p { display: -webkit-box; max-width: 760px; margin-top: 3px; overflow: hidden; color: var(--text-2); font-size: 11px; line-height: 1.45; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.student-question-score { min-width: 92px; text-align: right; }
.student-question-score strong, .student-question-score span { display: block; }
.student-question-score span, .student-question-time { color: var(--text-3); font-size: 11px; }
.student-question-time { white-space: nowrap; }
.empty-row { padding: 24px !important; color: var(--text-3); text-align: center; }
.analytics-error { display: flex; align-items: center; gap: 12px; }
.analytics-error .error-msg { margin: 0; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
.muted { color: var(--text-3); }
@media (max-width: 820px) {
  .analytics-grid { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 600px) {
  .analytics-head { align-items: flex-start; flex-direction: column; gap: 12px; }
  .section-heading, .student-tools { align-items: stretch; flex-direction: column; }
  .student-search input { width: 100%; }
  .student-question-result { grid-template-columns: minmax(0, 1fr) auto; }
  .student-question-score { text-align: left; }
  .student-question-time { white-space: normal; }
  .student-table { min-width: 650px; }
}
</style>
