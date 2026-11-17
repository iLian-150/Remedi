<template>
  <div class="page dashboard-page">
    <section class="card dashboard-toolbar" aria-labelledby="dashboard-review-title">
      <div class="review-status">
        <span class="review-icon" :class="{ 'has-pending': pendingReview?.count }">
          <AppIcon name="clipboard" :size="20" />
        </span>
        <div>
          <h2 id="dashboard-review-title">待复核</h2>
          <p v-if="reviewLoading" class="status-text" role="status">正在读取待复核题目…</p>
          <p v-else-if="reviewFailed" class="status-text" role="alert">待复核题目加载失败</p>
          <p v-else-if="pendingReview" class="status-text tnum">
            {{ pendingReview.count ? `${pendingReview.count} 道题` : '暂无待复核题目' }}
          </p>
        </div>
      </div>
      <div class="toolbar-actions">
        <button v-if="reviewFailed" type="button" class="btn secondary" @click="loadReviews">重试</button>
        <router-link v-else-if="pendingReview?.count" class="btn secondary" :to="reviewLocation">
          去复核 <AppIcon name="chevron-right" :size="15" />
        </router-link>
        <router-link class="btn" to="/teacher/assignments/new">
          <AppIcon name="plus" :size="17" /> 发布作业
        </router-link>
      </div>
    </section>

    <div class="dashboard-grid">
      <TeachingPlanCard />

      <div class="dashboard-side">
        <section class="card" aria-labelledby="recent-assignments-title">
          <header class="section-header">
            <h2 id="recent-assignments-title"><AppIcon name="chart" :size="18" /> 近期批改作业</h2>
            <router-link class="section-link" to="/teacher/assignments/manage" @click="teacher.setAssignmentDateFilter('')">
              作业管理 <AppIcon name="chevron-right" :size="14" />
            </router-link>
          </header>
          <p v-if="assignmentsLoading" class="loading" role="status">正在读取作业进度…</p>
          <div v-else-if="assignmentsFailed" class="section-error">
            <p class="error-msg" role="alert">作业进度加载失败</p>
            <button type="button" class="btn secondary small" @click="loadAssignments">重试</button>
          </div>
          <ul v-else-if="recentAssignments.length" class="dashboard-list">
            <li v-for="assignment in recentAssignments" :key="assignment.assignment_id">
              <router-link
                class="dashboard-row"
                :to="`/teacher/assignments/${assignment.assignment_id}/analytics`"
              >
                <span class="row-content">
                  <strong>{{ assignment.assignment_title || '未命名作业' }}</strong>
                  <span v-if="assignment.recipient_student_count" class="assignment-progress">
                    <span class="status-text">整份已交</span>
                    <progress
                      :value="assignment.submission_percent"
                      max="100"
                      :aria-label="`${assignment.assignment_title || '作业'}整份已交比例`"
                    />
                    <span class="tnum">{{ assignment.submission_percent }}%</span>
                  </span>
                  <span v-else class="status-text">暂无接收学生</span>
                </span>
                <AppIcon name="chevron-right" :size="16" class="row-arrow" />
              </router-link>
            </li>
          </ul>
          <p v-else class="empty">暂无已批改的作业</p>
        </section>

        <section class="card" aria-labelledby="attention-title">
          <header class="section-header">
            <h2 id="attention-title"><AppIcon name="users" :size="18" /> 需关注学生</h2>
            <router-link class="section-link" to="/teacher/students">
              学生管理 <AppIcon name="chevron-right" :size="14" />
            </router-link>
          </header>
          <p v-if="summaryLoading" class="loading" role="status">正在读取学生学情…</p>
          <div v-else-if="summaryFailed" class="section-error">
            <p class="error-msg" role="alert">学生学情加载失败</p>
            <button type="button" class="btn secondary small" @click="loadSummary">重试</button>
          </div>
          <ul v-else-if="summary?.attention_students.length" class="dashboard-list">
            <li v-for="student in summary.attention_students" :key="student.id">
              <router-link class="dashboard-row" :to="`/teacher/students/${student.id}`">
                <span class="row-content">
                  <strong>{{ student.name }}</strong>
                  <span class="status-text">{{ student.reason }}</span>
                </span>
                <AppIcon name="chevron-right" :size="16" class="row-arrow" />
              </router-link>
            </li>
          </ul>
          <p v-else class="empty">暂无需要跟进的学生</p>
        </section>
      </div>
    </div>

    <details v-if="summary" class="card dashboard-details" @toggle="onDetailsToggle">
      <summary>
        <AppIcon name="report" :size="18" /> 更多学情数据
        <AppIcon name="chevron-down" :size="16" class="details-chevron" />
      </summary>
      <div v-if="detailsOpen" class="detail-body">
        <dl class="detail-metrics tnum">
          <div><dt>学生人数</dt><dd>{{ summary.students.length }}</dd></div>
          <div><dt>累计错因记录</dt><dd>{{ summary.total_errors }}</dd></div>
          <div><dt>反复出错记录</dt><dd>{{ summary.stubborn_errors }}</dd></div>
          <div v-if="summary.repair_rate?.total_knowledge_point_pairs">
            <dt>班级知识修复率</dt>
            <dd>{{ formatRate(summary.repair_rate.class_repair_rate) }}</dd>
          </div>
        </dl>

        <div class="detail-columns">
          <section aria-labelledby="knowledge-records-title">
            <h3 id="knowledge-records-title">知识点错因记录</h3>
            <ul v-if="knowledgePoints.length" class="dashboard-list">
              <li v-for="point in knowledgePoints" :key="pointKey(point)" class="detail-row">
                <strong>{{ subjectLabel(point.subject) }} · {{ point.knowledge_point || '待归类' }}</strong>
                <span class="status-text tnum">
                  {{ point.errors }} 条错因记录 · {{ point.submissions }} 次提交
                  <template v-if="repairByPoint.has(pointKey(point))"> · {{ repairByPoint.get(pointKey(point)) }}</template>
                </span>
              </li>
            </ul>
            <p v-else class="empty">暂无知识点错因记录</p>
          </section>

          <section aria-labelledby="frequent-questions-title">
            <header class="section-header">
              <h3 id="frequent-questions-title">高频错题</h3>
              <select v-if="summary.top_questions.length > 5" v-model.number="topQuestionCount" class="question-limit" aria-label="显示题数">
                <option :value="5">前 5 道</option>
                <option :value="10">前 10 道</option>
                <option v-if="summary.top_questions.length > 10" :value="20">前 20 道</option>
              </select>
            </header>
            <ol v-if="summary.top_questions.length" class="dashboard-list">
              <li v-for="question in summary.top_questions.slice(0, topQuestionCount)" :key="question.question_id" class="detail-row">
                <strong>{{ question.stem }}</strong>
                <span class="status-text tnum">
                  {{ subjectLabel(question.subject) }}<template v-if="question.knowledge_point"> · {{ question.knowledge_point }}</template>
                  · {{ question.student_count }} 人出错 · {{ question.error_count }} 条错因记录
                </span>
              </li>
            </ol>
            <p v-else class="empty">暂无高频错题</p>
          </section>
        </div>
        <section v-if="summary.recent_error_types.length" aria-labelledby="recent-errors-title">
          <h3 id="recent-errors-title">最近 100 条错因分布</h3>
          <ul class="error-type-list tnum">
            <li v-for="entry in summary.recent_error_types" :key="entry.name">
              <ErrorTypeBadge :type="entry.name" />{{ entry.value }} 条
            </li>
          </ul>
        </section>
      </div>
    </details>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { KnowledgePointStat, TeacherAIGradingAssignmentItem, TeacherDashboardSummary } from '../../api/types'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import TeachingPlanCard from '../../components/TeachingPlanCard.vue'
import AppIcon from '../../components/icons/AppIcon.vue'
import { useTeacherStore } from '../../stores/teacher'
import { getSubjectLabel } from '../../utils/subjectLabels'

const teacher = useTeacherStore()
const pendingReview = ref<Awaited<ReturnType<typeof teacher.fetchPendingReviewSummary>> | null>(null)
const recentAssignments = ref<TeacherAIGradingAssignmentItem[]>([])
const summary = ref<TeacherDashboardSummary | null>(null)
const reviewLoading = ref(true)
const assignmentsLoading = ref(true)
const summaryLoading = ref(true)
const reviewFailed = ref(false)
const assignmentsFailed = ref(false)
const summaryFailed = ref(false)
const detailsOpen = ref(false)
const topQuestionCount = ref(10)

const reviewLocation = computed(() => {
  const submissionId = pendingReview.value?.latest_submission_id
  return {
    path: '/teacher/submissions',
    query: submissionId == null ? {} : { submission_id: String(submissionId) },
  }
})

function subjectLabel(subject: string) {
  return getSubjectLabel(subject, subject || '其他')
}

function pointKey(point: Pick<KnowledgePointStat, 'subject' | 'knowledge_point'>) {
  return `${point.subject}:${point.knowledge_point}`
}

function formatRate(rate: number) {
  return `${Math.round(rate * 100)}%`
}

const knowledgePoints = computed(() =>
  [...(summary.value?.knowledge_points ?? [])].sort((a, b) => b.errors - a.errors),
)
const repairByPoint = computed(() => new Map(
  (summary.value?.repair_rate?.knowledge_points ?? []).map((point) => [
    pointKey(point),
    `已修复 ${point.students_fixed}/${point.students_errored} 人`,
  ]),
))

function onDetailsToggle(event: Event) {
  detailsOpen.value = (event.currentTarget as HTMLDetailsElement).open
}

async function loadReviews() {
  reviewLoading.value = true
  reviewFailed.value = false
  try {
    pendingReview.value = await teacher.fetchPendingReviewSummary()
  } catch {
    reviewFailed.value = true
  } finally {
    reviewLoading.value = false
  }
}

async function loadAssignments() {
  assignmentsLoading.value = true
  assignmentsFailed.value = false
  try {
    const page = await teacher.fetchAIGradingAssignments({ limit: 3, offset: 0 })
    recentAssignments.value = page.items
  } catch {
    assignmentsFailed.value = true
  } finally {
    assignmentsLoading.value = false
  }
}

async function loadSummary() {
  summaryLoading.value = true
  summaryFailed.value = false
  try {
    summary.value = await teacher.fetchDashboardSummary(20)
  } catch {
    summaryFailed.value = true
  } finally {
    summaryLoading.value = false
  }
}

onMounted(() => {
  void loadReviews()
  void loadAssignments()
  void loadSummary()
})
</script>

<style scoped>
.dashboard-page { padding-block-start: 12px; }
.dashboard-page .card { min-width: 0; margin-bottom: 0; }
.dashboard-toolbar,
.review-status,
.toolbar-actions,
.section-header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.dashboard-toolbar {
  justify-content: space-between;
  flex-wrap: wrap;
  padding-block: 16px;
}
.review-icon {
  display: grid;
  flex: 0 0 42px;
  height: 42px;
  place-items: center;
  border-radius: var(--radius-control);
  background: var(--surface-2);
  color: var(--text-2);
}
.review-icon.has-pending { background: var(--amber-bg); color: var(--amber-strong); }
.dashboard-page h2 { font-size: 16px; font-weight: 700; }
.status-text { color: var(--text-2); font-size: 13px; }
.toolbar-actions { flex-wrap: wrap; }

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
  align-items: start;
  gap: 16px;
  margin-top: 16px;
}
.dashboard-side { display: grid; gap: 16px; min-width: 0; }
.section-header { justify-content: space-between; flex-wrap: wrap; }
.section-header h2 { display: flex; align-items: center; gap: 8px; }
.section-header h2 svg { color: var(--primary); }
.section-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 36px;
  color: var(--primary);
  font-size: 13px;
  font-weight: 620;
}
.dashboard-list { list-style: none; }
.dashboard-list > li + li { border-top: 1px solid var(--border); }
.dashboard-row {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 52px;
  padding: 10px 4px;
  border-radius: var(--radius-control);
}
@media (hover: hover) {
  .dashboard-row:hover { background: var(--surface-2); }
  .section-link:hover { color: var(--primary-dark); }
}
.row-content { display: grid; flex: 1; gap: 4px; min-width: 0; overflow-wrap: anywhere; }
.row-content strong, .detail-row strong { font-size: 14px; font-weight: 640; }
.row-arrow { color: var(--text-2); }
.assignment-progress {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  color: var(--primary-dark);
  font-size: 13px;
  font-weight: 620;
}
.assignment-progress progress {
  appearance: none;
  width: 100%;
  height: 5px;
  border: 0;
  border-radius: var(--radius-pill);
  background: var(--border);
}
.assignment-progress progress::-webkit-progress-bar { border-radius: var(--radius-pill); background: var(--border); }
.assignment-progress progress::-webkit-progress-value { border-radius: var(--radius-pill); background: var(--primary); }
.assignment-progress progress::-moz-progress-bar { border-radius: var(--radius-pill); background: var(--primary); }
.dashboard-side .empty, .dashboard-side .loading, .detail-body .empty { padding-block: 16px; }
.section-error { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.section-error .error-msg { margin: 0; }

.dashboard-details { margin-top: 16px; padding-block: 12px; }
.dashboard-details > summary {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  border-radius: var(--radius-control);
  font-weight: 650;
  cursor: pointer;
  list-style: none;
}
.dashboard-details > summary::-webkit-details-marker { display: none; }
.details-chevron { margin-left: auto; color: var(--text-2); }
.dashboard-details[open] .details-chevron { transform: rotate(180deg); }
.detail-body { display: grid; gap: 20px; padding-block: 12px; }
.detail-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 145px), 1fr));
  gap: 12px;
  padding: 12px 16px;
  border-radius: var(--radius-control);
  background: var(--surface-2);
}
.detail-metrics dt { color: var(--text-2); font-size: 13px; }
.detail-metrics dd { font-size: 20px; font-weight: 700; }
.detail-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; }
.detail-body h3 { margin-bottom: 4px; }
.detail-row { display: grid; gap: 4px; padding-block: 10px; overflow-wrap: anywhere; }
.question-limit { width: auto; min-height: 36px; padding: 5px 8px; font-size: 13px; }
.error-type-list { display: flex; flex-wrap: wrap; gap: 8px 14px; list-style: none; font-size: 13px; }
.error-type-list li { display: flex; align-items: center; }

@media (max-width: 760px) {
  .dashboard-grid, .detail-columns { grid-template-columns: minmax(0, 1fr); }
}
</style>
