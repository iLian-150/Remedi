<template>
  <div class="page ai-grading-page">
    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="success" class="ok-msg">{{ success }}</div>

    <section class="card grading-controls">
      <div class="grading-toolbar">
        <label class="search-field">
          <span>搜索</span>
          <input
            v-model="keyword"
            type="text"
            placeholder="学生、作业、题目或知识点"
            @keydown.enter="search"
          />
        </label>
        <button class="btn small" :disabled="loading" @click="search">查询</button>
      </div>

      <form class="threshold-settings" @submit.prevent="saveThreshold">
        <div class="threshold-copy">
          <label for="grading-threshold">低分标记线</label>
        </div>
        <div class="threshold-controls">
          <span class="threshold-prefix">低于</span>
          <div class="threshold-input-wrap">
            <input id="grading-threshold" v-model="thresholdInput" type="number" min="0" max="100" step="1" aria-label="低分标记线（百分比）" required :disabled="savingThreshold || !thresholdLoaded" />
            <span aria-hidden="true">%</span>
          </div>
          <button class="btn secondary" type="submit" :disabled="savingThreshold || !thresholdLoaded">{{ savingThreshold ? '保存中…' : '保存' }}</button>
        </div>
      </form>
    </section>

    <section class="card grading-list">
      <header class="grading-stage-head">
        <div class="grading-breadcrumb">
          <button v-if="stage !== 'assignments'" type="button" @click="backToAssignments">全部作业</button>
          <strong v-else>作业</strong>
          <template v-if="selectedAssignment">
            <AppIcon name="chevron-right" :size="15" />
            <button v-if="stage === 'questions'" type="button" @click="backToStudents">{{ selectedAssignment.assignment_title }}</button>
            <strong v-else>{{ selectedAssignment.assignment_title }}</strong>
          </template>
          <template v-if="selectedStudent">
            <AppIcon name="chevron-right" :size="15" />
            <strong>{{ selectedStudent.student.name }}</strong>
          </template>
        </div>
      </header>

      <div v-if="loading" class="loading">加载中…</div>
      <div v-else-if="stage === 'assignments' && !assignments.length" class="empty">暂无 AI 批改作业。</div>
      <div v-else-if="stage === 'assignments'" class="grading-entry-grid">
        <button
          v-for="assignment in assignments"
          :key="assignment.assignment_id"
          type="button"
          class="grading-entry assignment-entry"
          @click="selectAssignment(assignment)"
        >
          <span class="grading-entry-icon"><AppIcon name="clipboard" :size="19" /></span>
          <span class="grading-entry-main">
            <strong>{{ assignment.assignment_title || '未命名作业' }}</strong>
            <span>{{ assignment.student_count }} 名学生 · {{ assignment.answer_count }} 道已批改题目</span>
          </span>
          <span class="grading-entry-date tnum">最近提交 {{ fmtTime(assignment.latest_submitted_at) }}</span>
          <AppIcon class="grading-entry-arrow" name="chevron-right" :size="17" />
        </button>
      </div>

      <div v-else-if="stage === 'students' && !students.length" class="empty">这份作业暂无 AI 批改记录。</div>
      <div v-else-if="stage === 'students'" class="grading-entry-grid student-entry-grid">
        <button
          v-for="entry in students"
          :key="entry.student.id"
          type="button"
          class="grading-entry student-entry"
          @click="selectStudent(entry)"
        >
          <span class="grading-entry-icon"><AppIcon name="users" :size="19" /></span>
          <span class="grading-entry-main">
            <strong>{{ entry.student.name }}</strong>
            <span>学号 {{ entry.student.student_no || '—' }} · {{ entry.answer_count }} 道已批改题目</span>
          </span>
          <span class="grading-entry-date tnum">最近提交 {{ fmtTime(entry.latest_submitted_at) }}</span>
          <AppIcon class="grading-entry-arrow" name="chevron-right" :size="17" />
        </button>
      </div>

      <div v-else-if="!items.length" class="empty">该学生暂无已批改题目。</div>
      <div v-else class="table-scroll">
        <table class="table">
          <thead>
            <tr>
              <th>题目</th>
              <th>AI 得分</th>
              <th>批改状态</th>
              <th>时间</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in items"
              :key="item.submission_id"
              class="grading-row"
              :class="{ 'low-score-row': item.is_low_score }"
              @click="openDetail(item.submission_id)"
            >
              <td class="question-cell">
                <span>{{ item.question_stem || '暂无题目文本' }}</span>
                <small>{{ item.knowledge_point || item.subject }}</small>
              </td>
              <td class="score-cell tnum">
                <strong>{{ fmtScore(item.ai_score) }}</strong><span> / {{ fmtScore(item.question_max) }}</span>
                <small v-if="item.final_score !== null">教师定分 {{ fmtScore(item.final_score) }}</small>
              </td>
              <td>
                <span v-if="item.review_status === 'pending'" class="badge badge-amber">待二次批改</span>
                <span v-else-if="item.teacher_regraded" class="badge badge-blue">教师已二次批改</span>
                <span v-else class="badge badge-green">AI 已批改</span>
                <span v-if="item.error_count" class="error-count">{{ item.error_count }} 处错因</span>
                <span v-else class="table-sub">全对</span>
                <span v-if="item.is_low_score" class="badge badge-red low-score-badge">整份作业低于 {{ threshold }}%</span>
              </td>
              <td class="time-cell tnum">{{ fmtTime(item.submitted_at) }}</td>
              <td><button type="button" class="btn small secondary" @click.stop="openDetail(item.submission_id)">查看 / 修改</button></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="stageTotal > stagePageSize" class="pagination">
        <button class="btn small secondary" :disabled="stageOffset === 0 || loading" @click="changePage(-1)">上一页</button>
        <span class="tnum">{{ stageOffset + 1 }}–{{ Math.min(stageOffset + stageItemCount, stageTotal) }} / {{ stageTotal }}</span>
        <button class="btn small secondary" :disabled="stageOffset + stagePageSize >= stageTotal || loading" @click="changePage(1)">下一页</button>
      </div>
    </section>

    <div v-if="modalOpen" class="detail-mask" @click.self="closeDetail">
      <section class="detail-modal" role="dialog" aria-modal="true" aria-labelledby="detail-title">
        <header class="detail-header">
          <div>
            <h3 id="detail-title">AI 批改详情</h3>
            <p v-if="detail">{{ detail.assignment_title }} · {{ detail.student.name }} · {{ fmtTime(detail.submitted_at) }}</p>
          </div>
          <button class="detail-close" aria-label="关闭详情" @click="closeDetail">×</button>
        </header>

        <div v-if="detailLoading" class="detail-loading loading">加载诊断中…</div>
        <div v-else-if="detail" class="detail-body">
          <div class="detail-image">
            <a v-if="selectedItem?.image_url" :href="imageSrc(selectedItem.image_url)" target="_blank" rel="noopener noreferrer">
              <img :src="imageSrc(selectedItem.image_url)" :alt="selectedItem.image_name || '学生作答原图'" />
            </a>
            <div v-else class="image-empty">暂无作答原图</div>
          </div>

          <div class="detail-content">
            <section class="detail-panel">
              <div class="panel-title"><h4>题目</h4><span>{{ detail.question.knowledge_point || detail.question.subject }}</span></div>
              <p class="question-text">{{ detail.question.stem }}</p>
            </section>

            <section class="detail-panel">
              <div class="panel-title"><h4>解题过程</h4><span>{{ answerSteps.length }} 步</span></div>
              <div v-if="detail.process_check?.suspicious" class="process-note">
                <strong>过程提示</strong>
                <p v-for="signal in detail.process_check.signals" :key="signal.code">{{ signal.text }}</p>
                <small v-if="detail.process_check.final_answer || detail.process_check.reference_answer">
                  学生答案：{{ detail.process_check.final_answer ?? '—' }} · 参考答案：{{ detail.process_check.reference_answer ?? '—' }}
                </small>
              </div>
              <article v-for="step in answerSteps" :key="step.seq" class="answer-step" :class="{ wrong: step.status === 'error', right: step.status === 'ok' }">
                <div><strong>第 {{ step.seq }} 步</strong><span>{{ STEP_STATUS_TEXT[step.status] }}</span></div>
                <p>{{ step.text }}</p>
              </article>
              <p v-if="!answerSteps.length" class="table-sub">没有可展示的分步作答。</p>
            </section>

            <section v-if="detail.diagnosis.errors.length" class="detail-panel">
              <div class="panel-title"><h4>AI 错因</h4><span>{{ detail.diagnosis.errors.length }} 处</span></div>
              <article v-for="issue in detail.diagnosis.errors" :key="issue.id" class="issue-card">
                <div class="issue-meta">
                  <span>第 {{ issue.step_seq ?? '—' }} 步</span>
                  <ErrorTypeBadge :type="issue.error_type" />
                  <span class="conf-text tnum">置信度 {{ Math.round(issue.confidence * 100) }}%</span>
                </div>
                <p>{{ issue.detail || '暂无诊断说明。' }}</p>
                <p v-if="issue.step_text" class="table-sub">作答：{{ issue.step_text }}</p>
                <div class="correction-controls">
                  <label class="sr-only" :for="`error-type-${issue.id}`">修改错因分类</label>
                  <select :id="`error-type-${issue.id}`" v-model="correctionForms[issue.id].type">
                    <option value="">修改错因…</option>
                    <option v-for="type in ERROR_TYPES" :key="type" :value="type">{{ type }}</option>
                  </select>
                  <input v-model="correctionForms[issue.id].note" type="text" aria-label="纠错备注" placeholder="备注（可选）" />
                  <button class="btn small secondary" :disabled="!correctionForms[issue.id].type || correctingId === issue.id" @click="saveCorrection(issue.id)">
                    {{ correctingId === issue.id ? '保存中…' : '保存错因' }}
                  </button>
                </div>
              </article>
            </section>
            <section v-else class="detail-panel all-correct"><AppIcon name="check" :size="18" /> 这份作答没有识别到错因</section>

            <section v-if="detail.score" class="detail-panel score-editor">
              <div class="panel-title"><h4>教师二次批改</h4><span>本题满分 {{ fmtScore(detail.score.question_max) }} 分</span></div>
              <p class="ai-score-line">AI 评分 <strong class="tnum">{{ fmtScore(detail.score.ai_score) }}</strong> 分 · {{ detail.score.ok_steps }}/{{ detail.score.total_steps }} 步正确</p>
              <label for="regrade-score">教师确认分数</label>
              <div class="score-input-row">
                <input id="regrade-score" v-model="finalScoreInput" type="text" inputmode="decimal" />
                <span>分</span>
                <button type="button" class="chip-btn" @click="finalScoreInput = fmtScore(detail.score?.ai_score ?? null)">恢复 AI 分</button>
                <button type="button" class="chip-btn" @click="finalScoreInput = fmtScore(detail.score?.question_max ?? null)">满分</button>
              </div>
              <p v-if="detail.score.final_score !== null" class="table-sub">上次教师定分：{{ fmtScore(detail.score.final_score) }} 分</p>
              <button class="btn save-regrade" :disabled="savingRegrade" @click="saveRegrade">
                {{ savingRegrade ? '保存中…' : '保存二次批改' }}
              </button>
            </section>
          </div>
        </div>
        <div v-else class="detail-loading error-msg">{{ error || '详情加载失败。' }}</div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { useTeacherStore } from '../../stores/teacher'
import type {
  ReviewDetail,
  TeacherAIGradingAssignmentItem,
  TeacherAIGradingItem,
  TeacherAIGradingStudentItem,
} from '../../api/types'
import { ERROR_TYPES, STEP_STATUS_TEXT } from '../../api/types'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import AppIcon from '../../components/icons/AppIcon.vue'

const teacher = useTeacherStore()
const route = useRoute()
const assignmentPageSize = 12
const studentPageSize = 24
const pageSize = 50
const assignments = ref<TeacherAIGradingAssignmentItem[]>([])
const students = ref<TeacherAIGradingStudentItem[]>([])
const items = ref<TeacherAIGradingItem[]>([])
const assignmentTotal = ref(0)
const studentTotal = ref(0)
const questionTotal = ref(0)
const assignmentOffset = ref(0)
const studentOffset = ref(0)
const questionOffset = ref(0)
const selectedAssignment = ref<TeacherAIGradingAssignmentItem | null>(null)
const selectedStudent = ref<TeacherAIGradingStudentItem | null>(null)
const keyword = ref('')
const loading = ref(false)
const detailLoading = ref(false)
const modalOpen = ref(false)
const error = ref('')
const success = ref('')
const detail = ref<ReviewDetail | null>(null)
const selectedId = ref<number | null>(null)
const finalScoreInput = ref('')
const savingRegrade = ref(false)
const threshold = ref(60)
const thresholdInput = ref('60')
const thresholdLoaded = ref(false)
const savingThreshold = ref(false)
const correctingId = ref<number | null>(null)
const correctionForms = reactive<Record<number, { type: string; note: string }>>({})
const detailListItem = ref<TeacherAIGradingItem | null>(null)
let listRequest = 0
let detailRequest = 0

const stage = computed(() => selectedStudent.value ? 'questions' : selectedAssignment.value ? 'students' : 'assignments')
const stageTotal = computed(() => stage.value === 'assignments' ? assignmentTotal.value : stage.value === 'students' ? studentTotal.value : questionTotal.value)
const stageOffset = computed(() => stage.value === 'assignments' ? assignmentOffset.value : stage.value === 'students' ? studentOffset.value : questionOffset.value)
const stagePageSize = computed(() => stage.value === 'assignments' ? assignmentPageSize : stage.value === 'students' ? studentPageSize : pageSize)
const stageItemCount = computed(() => stage.value === 'assignments' ? assignments.value.length : stage.value === 'students' ? students.value.length : items.value.length)
const selectedItem = computed(() =>
  items.value.find((item) => item.submission_id === selectedId.value)
  ?? (detailListItem.value?.submission_id === selectedId.value ? detailListItem.value : null),
)
const answerSteps = computed(() => detail.value?.diagnosis.steps.filter((step) => step.status !== 'stem') ?? [])

function fmtScore(score: number | null): string {
  return score === null ? '—' : String(Math.round(score * 10) / 10)
}
function fmtTime(value: string): string { return value.replace('T', ' ').slice(0, 16) }
function imageSrc(path: string): string {
  if (/^https?:\/\//i.test(path)) return path
  const base = String(import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
  return `${base}${path.startsWith('/') ? path : `/${path}`}`
}
function errDetail(value: unknown): string {
  const message = (value as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof message === 'string' ? message : '请稍后重试。'
}

async function loadAssignments(newOffset = assignmentOffset.value) {
  const request = ++listRequest
  assignmentOffset.value = newOffset
  loading.value = true
  error.value = ''
  try {
    const page = await teacher.fetchAIGradingAssignments({
      limit: assignmentPageSize,
      offset: newOffset,
      keyword: keyword.value.trim() || undefined,
    })
    if (request !== listRequest) return false
    assignments.value = page.items
    assignmentTotal.value = page.total
    threshold.value = page.low_score_threshold
    if (!thresholdLoaded.value) {
      thresholdInput.value = String(page.low_score_threshold)
      thresholdLoaded.value = true
    }
    return true
  } catch (cause) {
    if (request !== listRequest) return false
    error.value = `AI 批改作业加载失败：${errDetail(cause)}`
    return false
  } finally {
    if (request === listRequest) loading.value = false
  }
}

async function loadStudents(newOffset = studentOffset.value) {
  if (!selectedAssignment.value) return false
  const request = ++listRequest
  studentOffset.value = newOffset
  loading.value = true
  error.value = ''
  try {
    const page = await teacher.fetchAIGradingStudents(selectedAssignment.value.assignment_id, {
      limit: studentPageSize,
      offset: newOffset,
      keyword: keyword.value.trim() || undefined,
    })
    if (request !== listRequest) return false
    students.value = page.items
    studentTotal.value = page.total
    return true
  } catch (cause) {
    if (request !== listRequest) return false
    error.value = `学生列表加载失败：${errDetail(cause)}`
    return false
  } finally {
    if (request === listRequest) loading.value = false
  }
}

async function load(newOffset = questionOffset.value) {
  const request = ++listRequest
  questionOffset.value = newOffset
  loading.value = true
  error.value = ''
  try {
    const page = await teacher.fetchAIGradings({
      limit: pageSize,
      offset: newOffset,
      keyword: keyword.value.trim() || undefined,
      assignment_id: selectedAssignment.value?.assignment_id,
      student_id: selectedStudent.value?.student.id,
    })
    if (request !== listRequest) return false
    items.value = page.items
    questionTotal.value = page.total
    threshold.value = page.low_score_threshold
    if (!thresholdLoaded.value) {
      thresholdInput.value = String(page.low_score_threshold)
      thresholdLoaded.value = true
    }
    return true
  } catch (cause) {
    if (request !== listRequest) return false
    error.value = `题目列表加载失败：${errDetail(cause)}`
    return false
  } finally {
    if (request === listRequest) loading.value = false
  }
}

async function refreshCurrentStage(): Promise<boolean> {
  if (stage.value === 'assignments') return loadAssignments(assignmentOffset.value)
  if (stage.value === 'students') return loadStudents(studentOffset.value)
  return load(questionOffset.value)
}

function search() {
  selectedAssignment.value = null
  selectedStudent.value = null
  students.value = []
  items.value = []
  studentOffset.value = 0
  questionOffset.value = 0
  void loadAssignments(0)
}

function selectAssignment(assignment: TeacherAIGradingAssignmentItem) {
  selectedAssignment.value = assignment
  selectedStudent.value = null
  students.value = []
  items.value = []
  studentOffset.value = 0
  questionOffset.value = 0
  void loadStudents(0)
}

function selectStudent(entry: TeacherAIGradingStudentItem) {
  selectedStudent.value = entry
  items.value = []
  questionOffset.value = 0
  void load(0)
}

function backToAssignments() {
  if (stage.value === 'assignments') return
  listRequest += 1
  loading.value = false
  selectedAssignment.value = null
  selectedStudent.value = null
  students.value = []
  items.value = []
}

function backToStudents() {
  listRequest += 1
  loading.value = false
  selectedStudent.value = null
  items.value = []
}

function changePage(direction: -1 | 1) {
  const nextOffset = Math.max(0, stageOffset.value + direction * stagePageSize.value)
  if (stage.value === 'assignments') void loadAssignments(nextOffset)
  else if (stage.value === 'students') void loadStudents(nextOffset)
  else void load(nextOffset)
}

async function saveThreshold() {
  const raw = String(thresholdInput.value).trim()
  const value = Number(raw)
  if (!raw || !Number.isInteger(value) || value < 0 || value > 100) {
    error.value = '低分标记线请输入 0 到 100 之间的整数。'
    return
  }
  savingThreshold.value = true
  error.value = ''
  success.value = ''
  try {
    await teacher.updateGradingThreshold(value)
    thresholdInput.value = String(value)
    if (await refreshCurrentStage()) success.value = '低分标记线已保存。'
    else error.value = '低分标记线已保存，列表刷新失败，请重新查询。'
  } catch (cause) {
    error.value = `低分标记线保存失败：${errDetail(cause)}`
  } finally {
    savingThreshold.value = false
  }
}

async function openDetail(submissionId: number) {
  const request = ++detailRequest
  selectedId.value = submissionId
  detailListItem.value = items.value.find((item) => item.submission_id === submissionId)
    ?? (detailListItem.value?.submission_id === submissionId ? detailListItem.value : null)
  modalOpen.value = true
  detailLoading.value = true
  detail.value = null
  error.value = ''
  try {
    const result = await teacher.fetchReviewDetail(submissionId)
    if (request !== detailRequest || selectedId.value !== submissionId) return
    detail.value = result
    finalScoreInput.value = fmtScore(result.score?.final_score ?? result.score?.ai_score ?? null)
    result.diagnosis.errors.forEach((issue) => {
      if (!correctionForms[issue.id]) correctionForms[issue.id] = { type: '', note: '' }
    })
    if (!detailListItem.value) {
      try {
        const page = await teacher.fetchAIGradings({ limit: 1, offset: 0, submission_id: submissionId })
        if (request === detailRequest && selectedId.value === submissionId) {
          detailListItem.value = page.items[0] ?? null
        }
      } catch {
        // 深链详情本身仍可展示；列表摘要失败时只隐藏原图预览。
      }
    }
  } catch (cause) {
    if (request === detailRequest) error.value = `详情加载失败：${errDetail(cause)}`
  } finally {
    if (request === detailRequest) detailLoading.value = false
  }
}

function closeDetail() {
  detailRequest += 1
  modalOpen.value = false
  detail.value = null
  selectedId.value = null
}
function onKeydown(event: KeyboardEvent) { if (event.key === 'Escape' && modalOpen.value) closeDetail() }

async function saveCorrection(errorId: number) {
  const form = correctionForms[errorId]
  if (!form?.type || !selectedId.value) return
  correctingId.value = errorId
  error.value = ''
  try {
    await teacher.correctError(errorId, {
      error_type: form.type,
      teacher_note: form.note.trim() || undefined
    })
    form.type = ''
    form.note = ''
    success.value = '错因已更新。'
    await openDetail(selectedId.value)
    await refreshCurrentStage()
  } catch (cause) {
    error.value = `错因保存失败：${errDetail(cause)}`
  } finally {
    correctingId.value = null
  }
}

async function saveRegrade() {
  if (!selectedId.value || !detail.value?.score) return
  const submissionId = selectedId.value
  const raw = String(finalScoreInput.value ?? '').trim()
  const score = Number(raw)
  const max = detail.value.score.question_max
  if (!raw || !Number.isFinite(score) || score < 0 || score > max) {
    error.value = `分数需在 0 到 ${fmtScore(max)} 分之间。`
    return
  }
  savingRegrade.value = true
  error.value = ''
  try {
    await teacher.regradeAIGrading(submissionId, score)
    success.value = '二次批改已保存，学生已收到成绩更新提醒。'
    await refreshCurrentStage()
    await openDetail(submissionId)
  } catch (cause) {
    error.value = `二次批改保存失败：${errDetail(cause)}`
  } finally {
    savingRegrade.value = false
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  const preset = Number(route.query.submission_id)
  void loadAssignments(0)
  if (Number.isFinite(preset) && preset > 0) void openDetail(preset)
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.grading-controls { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); align-items: center; gap: 20px; padding: 16px 18px; border-radius: var(--radius-surface); }
.grading-toolbar { display: flex; min-width: 0; align-items: center; gap: 10px; flex-wrap: wrap; }
.search-field { display: flex; flex: 1 1 280px; min-width: 220px; align-items: center; gap: 10px; color: var(--text-2); font-size: 13px; white-space: nowrap; }
.search-field input { width: 100%; min-width: 0; border-radius: var(--radius-control); }
.threshold-settings { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 20px; flex-wrap: wrap; margin: 0; padding: 0 0 0 24px; border: 0; border-left: 1px solid var(--border); }
.threshold-copy { display: grid; gap: 3px; }
.threshold-copy label { font-weight: 600; }
.threshold-controls { display: flex; align-items: center; gap: 10px; }
.threshold-prefix { color: var(--text-2); font-size: 14px; white-space: nowrap; }
.threshold-input-wrap { position: relative; }
.threshold-input-wrap input {
  width: 104px; height: 42px; padding: 9px 32px 9px 12px;
  border: 1px solid var(--border); border-radius: var(--radius-control);
  background: var(--card); color: var(--text); font: inherit;
  font-variant-numeric: tabular-nums; appearance: textfield;
}
.threshold-input-wrap input::-webkit-inner-spin-button,
.threshold-input-wrap input::-webkit-outer-spin-button { appearance: none; margin: 0; }
.threshold-input-wrap span { position: absolute; right: 12px; top: 50%; transform: translateY(-50%); color: var(--text-2); pointer-events: none; }
.threshold-controls .btn { min-height: 42px; white-space: nowrap; }
.grading-list { padding: 0; overflow: hidden; }
.grading-stage-head { display: flex; min-height: 62px; align-items: center; padding: 14px 20px; border-bottom: 1px solid var(--border); }
.grading-breadcrumb { display: flex; min-width: 0; align-items: center; gap: 8px; color: var(--text-2); font-size: 14px; }
.grading-breadcrumb button { min-width: 0; overflow: hidden; padding: 0; border: 0; background: transparent; color: var(--primary); font: inherit; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
.grading-breadcrumb strong { min-width: 0; overflow: hidden; color: var(--text); font-size: 15px; font-weight: 680; text-overflow: ellipsis; white-space: nowrap; }
.grading-entry-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 390px), 1fr)); gap: 12px; padding: 18px 20px; }
.grading-entry {
  display: grid; min-width: 0; grid-template-columns: 42px minmax(0, 1fr) auto 18px; align-items: center; gap: 12px;
  padding: 14px; border: 1px solid var(--border); border-radius: var(--radius-surface); background: var(--card); color: var(--text); text-align: left; cursor: pointer;
  transition: border-color .16s ease, background-color .16s ease, box-shadow .16s ease;
}
.grading-entry:hover { border-color: var(--border-strong); background: var(--surface-2); box-shadow: var(--shadow); }
.grading-entry:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.grading-entry-icon { display: grid; width: 42px; height: 42px; place-items: center; border-radius: var(--radius-control); background: var(--primary-50); color: var(--primary); }
.grading-entry-main { display: grid; min-width: 0; gap: 5px; }
.grading-entry-main strong { overflow: hidden; font-size: 14px; font-weight: 680; text-overflow: ellipsis; white-space: nowrap; }
.grading-entry-main > span { overflow: hidden; color: var(--text-2); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.grading-entry-date { color: var(--text-3); font-size: 11px; white-space: nowrap; }
.grading-entry-arrow { color: var(--text-3); }
.grading-list > .loading, .grading-list > .empty { margin: 0; padding: 56px 20px; }
.table-scroll { overflow-x: auto; }
.grading-list .table { min-width: 760px; }
.grading-row { cursor: pointer; }
.grading-row td { vertical-align: top !important; }
.grading-row:hover td { background: var(--primary-50); }
.low-score-row td { background: #FFF7F7; }
.low-score-row:hover td { background: #FEECEC; }
.table-sub { display: block; margin-top: 4px; color: var(--text-3); font-size: 12px; }
.question-cell { max-width: 330px; }
.question-cell > span { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.question-cell small { display: block; margin-top: 4px; color: var(--text-3); }
.score-cell { white-space: nowrap; }
.score-cell strong { font-size: 16px; }
.score-cell > span { color: var(--text-3); }
.score-cell small { display: block; margin-top: 3px; color: var(--primary); }
.assignment-score { display: block; white-space: nowrap; }
.low-score-badge { margin-top: 4px; }
.error-count { display: block; margin-top: 5px; color: var(--red); font-size: 12px; }
.time-cell { white-space: nowrap; color: var(--text-2); font-size: 13px; }
.pagination { display: flex; justify-content: center; align-items: center; gap: 14px; padding: 16px; color: var(--text-2); font-size: 13px; }
.detail-mask { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: 18px; background: rgba(15, 23, 42, .48); }
.detail-modal { display: flex; flex-direction: column; width: min(1180px, 100%); max-height: min(92vh, 1000px); overflow: hidden; background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-panel); box-shadow: var(--shadow-lg); }
.detail-header { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 17px 22px; background: var(--card); border-bottom: 1px solid var(--border); }
.detail-header h3 { font-size: 18px; }
.detail-header p { margin-top: 2px; color: var(--text-2); font-size: 13px; }
.detail-close { width: 36px; height: 36px; border: 1px solid var(--border); border-radius: var(--radius-control); background: var(--card); color: var(--text-2); font-size: 24px; line-height: 1; cursor: pointer; }
.detail-body { display: grid; grid-template-columns: minmax(260px, .8fr) minmax(0, 1.2fr); gap: 16px; min-height: 0; padding: 16px; overflow: hidden; }
.detail-image { position: sticky; top: 0; align-self: start; min-height: 220px; max-height: calc(92vh - 100px); overflow: auto; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-control); }
.detail-image img { display: block; width: 100%; max-height: calc(92vh - 100px); object-fit: contain; }
.image-empty { display: grid; min-height: 220px; place-items: center; color: var(--text-3); font-size: 13px; }
.detail-content { display: flex; flex-direction: column; gap: 12px; min-width: 0; min-height: 0; overflow: auto; padding-right: 4px; }
.detail-panel { padding: 16px; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-control); }
.panel-title { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.panel-title h4 { font-size: 16px; }
.panel-title > span { color: var(--text-3); font-size: 12px; }
.question-text { white-space: pre-wrap; line-height: 1.8; overflow-wrap: anywhere; }
.answer-step { margin-top: 9px; padding: 11px 13px; border: 1px solid var(--border); border-left: 4px solid #D1D5DB; border-radius: var(--radius-control); }
.answer-step > div { display: flex; justify-content: space-between; color: var(--text-2); font-size: 12px; }
.answer-step p { margin-top: 5px; white-space: pre-wrap; overflow-wrap: anywhere; }
.answer-step.wrong { border-left-color: var(--red); background: #FFFBFB; }
.answer-step.right { border-left-color: var(--green); }
.process-note { margin-bottom: 12px; padding: 12px; background: var(--amber-bg); border-radius: var(--radius-control); color: var(--amber-strong); }
.process-note p { margin-top: 4px; }
.process-note small { display: block; margin-top: 5px; }
.issue-card { padding: 12px 0; border-top: 1px solid var(--border); }
.issue-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; color: var(--text-2); font-size: 12px; }
.issue-card > p { margin-top: 7px; white-space: pre-wrap; overflow-wrap: anywhere; }
.correction-controls { display: grid; grid-template-columns: 150px minmax(140px, 1fr) auto; gap: 8px; margin-top: 10px; }
.correction-controls select, .correction-controls input { width: 100%; min-width: 0; }
.all-correct { display: flex; align-items: center; gap: 8px; color: var(--green); }
.score-editor { border-color: #C7D2FE; }
.ai-score-line { margin-bottom: 13px; color: var(--text-2); font-size: 13px; }
.ai-score-line strong { color: var(--primary); font-size: 18px; }
.score-editor > label { display: block; margin-bottom: 5px; color: var(--text-2); font-size: 13px; }
.score-input-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.score-input-row > input { width: 130px; font-size: 18px; font-weight: 700; }
.score-input-row > span { color: var(--text-2); }
.chip-btn { padding: 6px 10px; border: 1px solid var(--border); border-radius: var(--radius-pill); background: #fff; color: var(--text-2); font-size: 12px; cursor: pointer; }
.chip-btn:hover { color: var(--primary); border-color: var(--primary); }
.save-regrade { margin-top: 13px; }
.detail-loading { padding: 40px; text-align: center; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
@media (max-width: 1100px) {
  .grading-controls { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .threshold-settings { margin: 0; padding: 12px 0 0; border-top: 1px solid var(--border); border-left: 0; }
}
@media (max-width: 760px) {
  .grading-entry-grid { grid-template-columns: minmax(0, 1fr); padding: 14px; }
  .grading-entry { grid-template-columns: 38px minmax(0, 1fr) 18px; gap: 10px; padding: 12px; }
  .grading-entry-icon { width: 38px; height: 38px; }
  .grading-entry-date { grid-column: 2; grid-row: 2; }
  .grading-entry-arrow { grid-column: 3; grid-row: 1 / 3; }
  .grading-stage-head { padding-inline: 14px; }
}
@media (max-width: 820px) {
  .page { padding: 16px; }
  .detail-mask { padding: 7px; }
  .detail-modal { max-height: 96vh; }
  .detail-body { display: flex; flex-direction: column; overflow: auto; }
  .detail-image { position: static; max-height: 32vh; flex: none; }
  .detail-image img { max-height: 32vh; }
  .detail-content { overflow: visible; }
}
@media (max-width: 540px) {
  .grading-toolbar .search-field { flex-basis: 100%; }
  .grading-toolbar > .btn { margin-left: auto; }
  .threshold-settings { gap: 14px; }
  .threshold-controls { width: 100%; }
  .correction-controls { grid-template-columns: 1fr; }
  .detail-header { padding: 13px 15px; }
}
</style>
