<!-- 学生端订正：先读取轻量作业目录，进入作业后再分页读取错题；订正判定、
     已订正详情、变式验证沿用既有流程。右侧订正日历通过 store.correctionsDateFilter
     同步筛选目录和题目列表。 -->
<template>
  <div class="page">
    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载错题中…</div>

    <template v-else>
      <!-- 日期筛选状态栏（v0.9.1）：右侧栏订正日历选中某天时出现，与作业列表页同构 -->
      <div v-if="selectedDate" class="card filter-bar">
        <div class="filter-info">
          <span class="filter-title">正在看 {{ selectedDateLabel }} 的订正</span>
          <span class="filter-progress-text tnum">共 {{ correctionTotals.total }} 条 · 待订正 {{ correctionTotals.pending }} 条</span>
        </div>
        <button class="btn secondary small" @click="clearDateFilter">查看全部</button>
      </div>

      <template v-if="view === 'assignments'">
        <div class="correction-index-toolbar">
          <div class="correction-status-tabs" role="group" aria-label="作业订正状态">
            <button
              type="button"
              :aria-pressed="assignmentStatus === 'pending'"
              :class="{ active: assignmentStatus === 'pending' }"
              @click="assignmentStatus = 'pending'"
            >待订正 <span class="tnum">{{ pendingAssignments.length }}</span></button>
            <button
              type="button"
              :aria-pressed="assignmentStatus === 'completed'"
              :class="{ active: assignmentStatus === 'completed' }"
              @click="assignmentStatus = 'completed'"
            >已完成 <span class="tnum">{{ completedAssignments.length }}</span></button>
          </div>
          <button
            v-if="awaitingVerifyKps.length"
            type="button"
            class="verify-index-action"
            :aria-expanded="awaitingVerifyExpanded"
            @click="awaitingVerifyExpanded = !awaitingVerifyExpanded"
          >
            <AppIcon name="target" :size="16" /> 待验证 <span class="tnum">{{ awaitingVerifyKps.length }}</span>
          </button>
        </div>

        <section class="correction-ledger" aria-label="订正作业目录">
          <div class="correction-ledger-head" aria-hidden="true">
            <span>作业</span>
            <span>订正进度</span>
            <span>发布日期</span>
            <span></span>
          </div>
          <div v-if="assignmentLoading" class="ledger-empty">正在整理作业目录…</div>
          <template v-else-if="visibleAssignments.length">
            <button
              v-for="(assignment, index) in visibleAssignments"
              :key="assignment.assignment_id"
              type="button"
              class="correction-assignment-row"
              :aria-label="`${assignment.assignment_title}，已订正 ${assignment.total_count - assignment.pending_count} / ${assignment.total_count} 条，进入错题列表`"
              @click="openAssignment(assignment)"
            >
              <span class="assignment-index-cell">
                <span class="assignment-index-number tnum">{{ String(index + 1).padStart(2, '0') }}</span>
                <span class="assignment-index-copy">
                  <span class="assignment-subject-index">{{ assignmentSubjectLabel(assignment) }}</span>
                  <strong>{{ assignment.assignment_title }}</strong>
                </span>
              </span>
              <span class="assignment-progress-cell">
                <span class="assignment-progress-copy tnum">
                  <span>已订正 <strong>{{ assignment.total_count - assignment.pending_count }}/{{ assignment.total_count }}</strong></span>
                  <span v-if="assignment.pending_count" class="assignment-pending-count">待订正 {{ assignment.pending_count }}</span>
                  <span v-else class="assignment-complete-count">已完成</span>
                </span>
                <span class="assignment-progress-track" :class="{ complete: assignment.pending_count === 0 }" aria-hidden="true">
                  <span :style="{ width: `${assignmentProgress(assignment)}%` }"></span>
                </span>
              </span>
              <time class="assignment-latest-time" :datetime="assignment.published_at">{{ correctionDateLabel(assignment.published_at) }}</time>
              <AppIcon name="chevron-right" :size="17" class="assignment-row-arrow" />
            </button>
          </template>
          <div v-else-if="!error" class="ledger-empty">
            <template v-if="!assignmentSummaries.length && !selectedDate">
              暂无需要订正的题目，<router-link to="/student/assignments" class="empty-link">去做作业</router-link>。
            </template>
            <template v-else-if="!assignmentSummaries.length">这一天没有错题。</template>
            <template v-else-if="assignmentStatus === 'pending'">没有待订正的作业。</template>
            <template v-else>还没有已完成的作业。</template>
          </div>
        </section>

        <section v-if="awaitingVerifyExpanded && awaitingVerifyKps.length" class="verify-index-panel">
          <div v-for="kp in awaitingVerifyKps" :key="`${kp.subject}:${kp.knowledge_point}`" class="verify-kp-row">
            <span>{{ subjectName(kp.subject) }} · {{ kp.knowledge_point }}</span>
            <button class="btn small" :aria-label="`验证${subjectName(kp.subject)}${kp.knowledge_point}`" @click="startVerification(kp)">开始验证</button>
          </div>
          <VerifyPanel
            v-if="verifyTarget"
            :key="`index-${verifyTarget.subject}-${verifyTarget.knowledge_point}`"
            :knowledge-point="verifyTarget.knowledge_point"
            :subject="verifyTarget.subject"
            :source-error-id="verifyTarget.source_error_id"
            class="verify-panel-inline"
            @passed="onVerifyPassed"
            @close="verifyTarget = null"
          />
        </section>
      </template>

      <template v-else-if="view === 'questions'">
        <header class="correction-inner-header">
          <button class="back-link" @click="backToAssignments">
            <AppIcon name="chevron-left" :size="16" /> 返回作业
          </button>
        </header>
        <section class="correction-question-list" :aria-label="`${selectedAssignmentSummary?.assignment_title ?? '作业'}错题列表`">
          <button
            v-for="item in mistakes"
            :key="item.id"
            type="button"
            class="correction-question-row"
            :aria-label="`第 ${item.question_order} 题，${item.corrected ? '已订正，查看诊断' : '待订正'}：${item.question_stem}`"
            @click="openError(item)"
          >
            <span class="question-number tnum">{{ String(item.question_order).padStart(2, '0') }}</span>
            <span class="question-row-content">
              <strong>{{ item.question_stem || `第 ${item.question_order} 题` }}</strong>
              <span class="question-row-meta">
                <ErrorTypeBadge :type="item.error_type" />
                <span v-if="item.knowledge_point">{{ item.knowledge_point }}</span>
                <time :datetime="mistakeDateKey(item)">{{ dateLabelOf(item) }}</time>
              </span>
            </span>
            <span class="question-row-status" :class="{ complete: item.corrected }">{{ item.corrected ? '已订正' : '待订正' }}</span>
            <AppIcon name="chevron-right" :size="17" class="assignment-row-arrow" />
          </button>
          <div v-if="!mistakes.length && !error" class="ledger-empty">这份作业暂时没有错题。</div>
          <button
            v-if="hasMoreMistakes"
            type="button"
            class="load-more-corrections"
            :disabled="loadingMoreMistakes"
            @click="loadMoreCorrectionWall"
          >{{ loadingMoreMistakes ? '正在加载…' : `继续显示错题（${mistakes.length} / ${selectedAssignmentSummary?.total_count ?? mistakes.length}）` }}</button>
        </section>
      </template>

      <template v-else-if="view === 'work' && selectedError">
        <div class="work-bar">
          <button class="back-link" @click="backToQuestions">
            <AppIcon name="chevron-left" :size="16" /> 返回作业错题
          </button>
        </div>
        <div class="card">
          <h3>题目回顾</h3>
          <!-- v0.13.9：原来这里只有出错的一步、看不到原题——改成完整回顾：
               原来的题目 → 我当时的作答（错步在原步骤里原地标出）→ 解析。
               v0.13.10：正确答案与标准解题过程不在订正前直接给出（用户口径），
               先自己想、自己改，判定结果会告诉你对不对 -->
          <div class="review-block">
            <span class="review-label">原来的题目</span>
            <p class="review-stem">{{ selectedError.question_stem || '题目内容暂未记录' }}</p>
            <a v-if="selectedError.image_url" class="review-img-link" :href="imageHref(selectedError.image_url)" target="_blank" rel="noreferrer">查看上传原图</a>
          </div>
          <div class="review-block">
            <span class="review-label">我当时的作答</span>
            <ol v-if="origSteps.length" class="orig-steps">
              <li v-for="st in origSteps" :key="st.seq" :class="origStepClass(st)">
                <span class="orig-seq">{{ st.seq }}</span>
                <span class="orig-text">{{ st.text }}</span>
                <span v-if="st.status === 'error'" class="orig-flag">出错在这里</span>
              </li>
            </ol>
            <p v-else-if="selectedError.step_text" class="step-text">第 {{ selectedError.step_seq ?? '?' }} 步：{{ selectedError.step_text }}（这一步出错了）</p>
            <p v-else class="detail">原来的作答步骤暂未记录。</p>
          </div>
          <p class="detail"><strong>解析：</strong>{{ sanitizeStudentCopy(selectedError.detail ?? '') }}</p>
          <p style="margin-top: 10px">
            <ErrorTypeBadge :type="selectedError.error_type" />
            <span class="badge badge-blue">{{ subjectName(selectedError.question_subject) }}</span>
            <span class="badge badge-blue">{{ selectedError.knowledge_point }}</span>
            <span v-if="selectedError.corrected" class="badge badge-green">已订正</span>
            <span v-else-if="selectedError.is_stubborn" class="badge badge-amber">需要加固</span>
          </p>
        </div>

        <div class="card">
          <h3>我的订正</h3>
          <div class="form-row">
            <label>写出这一步的正确内容</label>
            <input v-model="content" type="text" :placeholder="correctionPlaceholder" />
          </div>
          <button class="btn" :disabled="submitting || !content.trim()" @click="submit">
            {{ submitting ? '判定中…' : '提交订正' }}
          </button>
        </div>

        <div v-if="result" class="card">
          <h3>判定结果</h3>
          <p v-if="result.is_correct === true"><span class="badge badge-green">订正成功</span></p>
          <p v-else-if="result.is_correct === false"><span class="badge badge-amber">再想一想</span></p>
          <p v-else><span class="badge badge-gray">待老师确认</span></p>
          <p v-if="result.is_correct === null" class="note">请把订正内容交给老师确认。</p>
          <p class="note hint">{{ result.note }}</p>
          <!-- 订正成功且该知识点待验证 → 页内打开变式题面板完成验证（通过才算已修复） -->
          <div v-if="result.can_verify && !justVerified" class="verify-cta">
            <button class="btn small inline-icon" @click="openResultVerify">
              <AppIcon name="target" :size="15" /> 做变式题
            </button>
          </div>
          <p v-else-if="result.can_verify && justVerified" class="verify-done-note">
            <AppIcon name="check" :size="15" /> 验证通过
          </p>
          <VerifyPanel
            v-if="verifyTarget"
            :key="`work-${verifyTarget.subject}-${verifyTarget.knowledge_point}`"
            :knowledge-point="verifyTarget.knowledge_point"
            :subject="verifyTarget.subject"
            :source-error-id="verifyTarget.source_error_id"
            class="verify-panel-inline"
            @passed="onVerifyPassed"
            @close="verifyTarget = null"
          />
          <div class="result-actions">
            <button class="btn secondary small inline-icon" @click="backToQuestions">
              <AppIcon name="chevron-left" :size="15" /> 返回作业错题
            </button>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStudentStore } from '../../stores/student'
import type {
  AwaitingVerificationKnowledgePoint,
  CorrectionResult,
  StepDiagnosis,
  StudentCorrectionAssignmentSummary,
  StudentCorrectionWallItem,
} from '../../api/types'
import { sanitizeStudentCopy } from '../../utils/errorType'
import { getSubjectLabel } from '../../utils/subjectLabels'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import AppIcon from '../../components/icons/AppIcon.vue'
import VerifyPanel from '../../components/VerifyPanel.vue'

const student = useStudentStore()
const route = useRoute()
const router = useRouter()
const requestedErrorId = Number(route.query.error_id)
const includeErrorId = Number.isSafeInteger(requestedErrorId) && requestedErrorId > 0 ? requestedErrorId : undefined
if (includeErrorId) student.setCorrectionsDateFilter('')

/** 作业目录使用轻量汇总；进入作业后才分页读取错题详情。 */
const assignmentSummaries = ref<StudentCorrectionAssignmentSummary[]>([])
const assignmentLoading = ref(false)
const assignmentStatus = ref<'pending' | 'completed'>('pending')
const awaitingVerifyExpanded = ref(false)
let assignmentRequestGeneration = 0
const mistakes = ref<StudentCorrectionWallItem[]>([])
const selectedErrorId = ref<number | ''>('')
const selectedAssignmentId = ref<number | null>(null)
const view = ref<'assignments' | 'questions' | 'work'>('assignments')
/** 订正日历选中的日期（yyyy-mm-dd，空 = 全部）：v0.9.1 起由右侧栏订正日历写入
 * store.correctionsDateFilter，本页只读消费（筛选状态条与列表都据此响应） */
const selectedDate = computed(() => student.correctionsDateFilter)
const correctionPageSize = 40
const hasMoreMistakes = ref(false)
const loadingMoreMistakes = ref(false)
const correctionCursor = ref<{ created_at: string; id: number } | null>(null)
const loadedMistakesById = reactive(new Map<number, StudentCorrectionWallItem>())
let correctionRequestGeneration = 0
const content = ref('')
const result = ref<CorrectionResult | null>(null)
const loading = ref(false)
const submitting = ref(false)
const error = ref('')

const selectedAssignmentSummary = computed(() =>
  assignmentSummaries.value.find(item => item.assignment_id === selectedAssignmentId.value) ?? null,
)
const pendingAssignments = computed(() => assignmentSummaries.value.filter(item => item.pending_count > 0))
const completedAssignments = computed(() => assignmentSummaries.value.filter(item => item.pending_count === 0))
const visibleAssignments = computed(() =>
  assignmentStatus.value === 'pending' ? pendingAssignments.value : completedAssignments.value,
)
const correctionTotals = computed(() => {
  if (selectedAssignmentSummary.value) {
    return {
      total: selectedAssignmentSummary.value.total_count,
      pending: selectedAssignmentSummary.value.pending_count,
    }
  }
  return assignmentSummaries.value.reduce((totals, item) => ({
    total: totals.total + item.total_count,
    pending: totals.pending + item.pending_count,
  }), { total: 0, pending: 0 })
})

/** 错题所属提交的日期键：优先后端 submitted_at，缺失时用错题产生时间兜底 */
function mistakeDateKey(item: StudentCorrectionWallItem): string {
  return (item.submitted_at ?? item.created_at).slice(0, 10)
}

const selectedDateLabel = computed(() => {
  if (!selectedDate.value) return ''
  const [y, m, d] = selectedDate.value.split('-')
  return `${y} 年 ${Number(m)} 月 ${Number(d)} 日`
})

/** 错题日期文案：如「10月7日」 */
function dateLabelOf(item: StudentCorrectionWallItem): string {
  const [, m, d] = mistakeDateKey(item).split('-')
  return `${Number(m)}月${Number(d)}日`
}

function assignmentSubjectLabel(assignment: StudentCorrectionAssignmentSummary): string {
  return [...new Set(assignment.subjects)].map(subjectName).join(' / ') || '综合'
}

function assignmentProgress(assignment: StudentCorrectionAssignmentSummary): number {
  return assignment.total_count > 0
    ? Math.round(((assignment.total_count - assignment.pending_count) / assignment.total_count) * 100)
    : 0
}

function correctionDateLabel(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : `${date.getMonth() + 1}月${date.getDate()}日`
}

function openAssignment(assignment: StudentCorrectionAssignmentSummary) {
  selectedAssignmentId.value = assignment.assignment_id
  student.setCorrectionPageTitle(assignment.assignment_title)
  selectedErrorId.value = ''
  view.value = 'questions'
  onSelect()
  void loadCorrectionWall(true)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function openError(item: StudentCorrectionWallItem) {
  if (item.corrected) {
    onViewNote(item.submission_id)
    return
  }
  selectedErrorId.value = item.id
  onSelect()
  view.value = 'work'
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function onViewNote(submissionId: number) {
  router.push({ path: '/student/diagnosis', query: { submission_id: submissionId } })
}

function backToAssignments() {
  assignmentStatus.value = selectedAssignmentSummary.value?.pending_count === 0 ? 'completed' : 'pending'
  student.setCorrectionPageTitle('')
  selectedAssignmentId.value = null
  selectedErrorId.value = ''
  view.value = 'assignments'
  onSelect()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function backToQuestions() {
  selectedErrorId.value = ''
  view.value = 'questions'
  onSelect()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function clearDateFilter() {
  student.setCorrectionsDateFilter('')
}

async function loadAssignmentSummaries() {
  const submittedOn = selectedDate.value || undefined
  const generation = ++assignmentRequestGeneration
  assignmentLoading.value = true
  error.value = ''
  try {
    const summaries = await student.fetchCorrectionAssignmentSummaries(submittedOn)
    if (generation !== assignmentRequestGeneration || selectedDate.value !== (submittedOn ?? '')) return
    assignmentSummaries.value = summaries
  } catch (e) {
    if (generation === assignmentRequestGeneration) {
      error.value = '作业目录加载失败，请确认后端已启动。'
      console.error(e)
    }
  } finally {
    if (generation === assignmentRequestGeneration) assignmentLoading.value = false
  }
}

async function loadCorrectionWall(reset = true, includeId?: number, assignmentIdOverride?: number | null) {
  const submittedOn = selectedDate.value || undefined
  const requestedAssignmentId = assignmentIdOverride === undefined
    ? selectedAssignmentId.value ?? undefined
    : assignmentIdOverride ?? undefined
  let cursor: { created_at: string; id: number } | null = null
  let generation = correctionRequestGeneration
  if (reset) {
    generation = ++correctionRequestGeneration
    mistakes.value = []
    loadedMistakesById.clear()
    hasMoreMistakes.value = false
    correctionCursor.value = null
    loading.value = true
    loadingMoreMistakes.value = false
  } else {
    if (!hasMoreMistakes.value || !correctionCursor.value || loadingMoreMistakes.value) return
    cursor = correctionCursor.value
    loadingMoreMistakes.value = true
  }
  error.value = ''

  try {
    const page = await student.fetchCorrectionWallPage({
      date: submittedOn,
      assignmentId: requestedAssignmentId,
      limit: correctionPageSize,
      beforeCreatedAt: cursor?.created_at,
      beforeId: cursor?.id,
      includeId: reset ? includeId : undefined,
    })
    if (generation !== correctionRequestGeneration
      || selectedDate.value !== (submittedOn ?? '')
      || selectedAssignmentId.value !== (requestedAssignmentId ?? null)) return

    if (reset) {
      mistakes.value = page.items
      loadedMistakesById.clear()
      for (const item of mistakes.value) loadedMistakesById.set(item.id, item)
      // 首屏可能额外包含深链错题，按时间恢复顺序；后续页由联合游标保证顺序。
      mistakes.value.sort((a, b) =>
        b.created_at.localeCompare(a.created_at) || b.id - a.id,
      )
    } else {
      for (const item of page.items) {
        if (loadedMistakesById.has(item.id)) continue
        mistakes.value.push(item)
        const loadedItem = mistakes.value[mistakes.value.length - 1]
        loadedMistakesById.set(loadedItem.id, loadedItem)
      }
    }
    const summary = assignmentSummaries.value.find(item => item.assignment_id === requestedAssignmentId)
    if (summary && page.total_count != null) summary.total_count = page.total_count
    if (summary && page.pending_count != null) summary.pending_count = page.pending_count
    hasMoreMistakes.value = page.has_more
    correctionCursor.value = page.next_cursor
    if (reset) syncSelection()
  } catch (e) {
    if (generation === correctionRequestGeneration) {
      error.value = reset
        ? '错题加载失败，请确认后端已启动。'
        : '继续加载错题失败，请重试。'
      console.error(e)
      if (reset) syncSelection()
    }
  } finally {
    if (generation === correctionRequestGeneration) {
      loading.value = false
      loadingMoreMistakes.value = false
    }
  }
}

function loadMoreCorrectionWall() {
  return loadCorrectionWall(false)
}

// 右栏日历点选后刷新作业目录；作业内页面也同步按日期重新读取错题。
watch(selectedDate, async () => {
  const assignmentId = selectedAssignmentId.value
  const includeId = view.value === 'work' && typeof selectedErrorId.value === 'number'
    ? selectedErrorId.value
    : undefined
  await loadAssignmentSummaries()
  if (assignmentId === null) return
  if (!assignmentSummaries.value.some(item => item.assignment_id === assignmentId)) {
    selectedAssignmentId.value = null
    student.setCorrectionPageTitle('')
    selectedErrorId.value = ''
    view.value = 'assignments'
    onSelect()
    return
  }
  void loadCorrectionWall(true, includeId, assignmentId)
})

function syncSelection() {
  if (view.value === 'work' && !loadedMistakesById.has(Number(selectedErrorId.value))) {
    view.value = selectedAssignmentId.value === null ? 'assignments' : 'questions'
    selectedErrorId.value = ''
    onSelect()
  }
}

// 工作区消费当前页的轻量错题记录；完整作答步骤仍按提交 ID 按需读取，避免
// 首屏请求携带错题本不需要的标准答案、相似错题和订正正文。
const selectedError = computed(() => loadedMistakesById.get(Number(selectedErrorId.value)) ?? null)
const correctionPlaceholder = computed(() => selectedError.value?.question_subject === 'math'
  ? '例如：2x=7-3'
  : '写出订正后的正确步骤、结论或答案')
function subjectName(subject: string) { return getSubjectLabel(subject, subject || '其他学科') }

// v0.13.9：题目回顾要展示「我当时的作答」全文——错题条目里只有出错的那一步，
// 完整原步骤在提交详情里（每步带判定状态），选中错题时按 submission_id 拉一次；
// 拉不到就降级为只显示出错步骤（模板里的 v-else 分支）
const origSteps = ref<StepDiagnosis[]>([])
let origLoadToken = 0
const origStepsBySubmission = new Map<number, Promise<StepDiagnosis[]>>()
async function loadOrigSteps() {
  const err = selectedError.value
  const token = ++origLoadToken
  origSteps.value = []
  if (!err) return
  const submissionId = err.submission_id
  let stepsRequest = origStepsBySubmission.get(submissionId)
  if (!stepsRequest) {
    stepsRequest = student.fetchSubmissionDetail(submissionId).then((detail) =>
      (detail.steps ?? []).filter((step) => step.status !== 'stem'),
    )
    origStepsBySubmission.set(submissionId, stepsRequest)
  }
  try {
    const steps = await stepsRequest
    if (token !== origLoadToken) return
    origSteps.value = steps
  } catch {
    if (origStepsBySubmission.get(submissionId) === stepsRequest) {
      origStepsBySubmission.delete(submissionId)
    }
    if (token === origLoadToken) origSteps.value = []
  }
}
watch(selectedError, () => { void loadOrigSteps() })

function origStepClass(st: StepDiagnosis) {
  return {
    'is-error': st.status === 'error',
    'is-dim': st.status === 'skipped' || st.status === 'unparseable'
  }
}

/** 原图链接（与错题本同口径：相对路径按 API 基址补全） */
function imageHref(value: string) {
  const base = import.meta.env.VITE_API_BASE_URL || ''
  return base ? `${base.replace(/\/+$/, '')}${value}` : value
}

// ---------- 二次验证（迁入本页：报告纯化后验证入口只在订正流里） ----------
/** 当前打开了变式题面板的知识点（空 = 未打开）；墙面待验证区与结果区共用这一个状态 */
const verifyTarget = ref<AwaitingVerificationKnowledgePoint | null>(null)
/** 本次订正后刚在页内完成了该知识点的验证（结果区 CTA 随之换成完成提示） */
const justVerified = ref(false)
/** 待验证知识点名单按学科区分，避免同名知识点串用验证记录。 */
const awaitingVerifyKps = ref<AwaitingVerificationKnowledgePoint[]>([])

async function loadAwaitingVerifyKps(requestedErrorId?: number) {
  try {
    awaitingVerifyKps.value = await student.fetchAwaitingVerificationKps()
    if (requestedErrorId) {
      verifyTarget.value = awaitingVerifyKps.value.find(kp => kp.source_error_id === requestedErrorId) ?? null
    }
  } catch (e) {
    console.error(e)
  }
}

function startVerification(kp: AwaitingVerificationKnowledgePoint) {
  awaitingVerifyExpanded.value = true
  verifyTarget.value = kp
}

/** 结果区入口：为刚订正对的这条错题所属知识点打开变式题面板 */
function openResultVerify() {
  const mistake = selectedError.value
  const kp = result.value?.knowledge_point ?? mistake?.knowledge_point ?? ''
  if (kp && mistake) {
    verifyTarget.value = {
      subject: mistake.question_subject,
      knowledge_point: kp,
      source_error_id: mistake.id,
    }
  }
}

/** 验证通过：刷新待验证名单（该知识点转为已修复后自动从名单消失） */
async function onVerifyPassed() {
  justVerified.value = true
  await loadAwaitingVerifyKps()
}

function onSelect() {
  content.value = ''
  result.value = null
  justVerified.value = false
  verifyTarget.value = null
}

async function submit() {
  if (!selectedErrorId.value) return
  submitting.value = true
  error.value = ''
  result.value = null
  justVerified.value = false
  verifyTarget.value = null
  try {
    result.value = await student.submitCorrection({
      error_id: Number(selectedErrorId.value),
      content: content.value.trim()
    })
    // 订正成功后同步当前页状态和跨页汇总计数；后续页面读取以服务端记录为准。
    if (result.value.is_correct === true) {
      const fixedMistake = loadedMistakesById.get(Number(selectedErrorId.value))
      if (fixedMistake && !fixedMistake.corrected) {
        fixedMistake.corrected = true
        const summary = assignmentSummaries.value.find(item => item.assignment_id === fixedMistake.assignment_id)
        if (summary) summary.pending_count = Math.max(0, summary.pending_count - 1)
      }
    }
  } catch (e) {
    error.value = '订正提交失败：' + errDetail(e)
    console.error(e)
  } finally {
    submitting.value = false
  }
}

function errDetail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof d === 'string' ? d : '请稍后重试。'
}

onMounted(async () => {
  student.setCorrectionPageTitle('')
  const verifyId = Number(route.query.verify_error_id)
  // 待验证知识点名单独立加载；接口失败不阻挡作业目录。
  void loadAwaitingVerifyKps(Number.isSafeInteger(verifyId) && verifyId > 0 ? verifyId : undefined)
  if (verifyId > 0) awaitingVerifyExpanded.value = true
  await loadAssignmentSummaries()
  if (includeErrorId) {
    // 深链只额外读取目标错题，随后直接打开对应作业的订正工作区。
    await loadCorrectionWall(true, includeErrorId, null)
    const includedError = loadedMistakesById.get(includeErrorId)
    if (includedError) {
      selectedAssignmentId.value = includedError.assignment_id
      student.setCorrectionPageTitle(includedError.assignment_title)
      selectedErrorId.value = includeErrorId
      view.value = 'work'
    }
  }
})

onBeforeUnmount(() => student.setCorrectionPageTitle(''))

</script>

<style scoped>
/* 日期筛选状态 */
.filter-bar {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  margin-bottom: 16px; padding: 14px 18px;
}
.filter-info { display: flex; align-items: center; gap: 14px; flex: 1; min-width: 240px; flex-wrap: wrap; }
.filter-title { font-size: 15px; font-weight: 700; }
.filter-progress-text { font-size: 13.5px; color: var(--text-2); }
.correction-index-toolbar {
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px;
  margin: 18px 0 10px;
}
.correction-status-tabs { display: flex; align-items: center; gap: 22px; }
.correction-status-tabs button {
  display: inline-flex; align-items: center; gap: 7px; padding: 9px 2px;
  border: 0; border-bottom: 2px solid transparent; background: transparent;
  color: var(--text-2); font: inherit; font-size: 14px; font-weight: 600; cursor: pointer;
}
.correction-status-tabs button.active { border-bottom-color: var(--primary); color: var(--primary-dark); }
.correction-status-tabs button span { color: var(--text-3); font-size: 12px; }
.correction-status-tabs button.active span { color: var(--primary); }
.verify-index-action {
  display: inline-flex; align-items: center; gap: 7px; min-height: 38px; padding: 7px 12px;
  border: 1px solid var(--border); border-radius: var(--radius-control); background: var(--card);
  color: var(--text-2); font: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
}
.verify-index-action:hover, .verify-index-action[aria-expanded="true"] { border-color: var(--border-strong); color: var(--primary); }
.correction-ledger, .correction-question-list {
  overflow: hidden; border: 1px solid var(--border); border-radius: var(--radius-surface);
  background: var(--card); box-shadow: var(--shadow);
}
.correction-ledger-head, .correction-assignment-row {
  display: grid; grid-template-columns: minmax(0, 1fr) minmax(210px, 280px) 112px 20px;
  align-items: center; gap: 20px; padding: 13px 18px;
}
.correction-ledger-head {
  background: var(--primary-50); border-bottom: 1px solid var(--border);
  color: var(--text-2); font-size: 12px; font-weight: 650;
}
.correction-ledger-head span:nth-child(2) { text-align: left; }
.correction-ledger-head span:nth-child(3) { text-align: right; }
.correction-assignment-row {
  width: 100%; border: 0; border-bottom: 1px solid var(--border); background: var(--card);
  color: var(--text); text-align: left; font: inherit; cursor: pointer;
  transition: background-color .15s ease;
}
.correction-assignment-row:last-child { border-bottom: 0; }
.correction-assignment-row:hover { background: color-mix(in srgb, var(--primary-50) 55%, white); }
.assignment-index-cell { display: flex; align-items: center; min-width: 0; gap: 13px; }
.assignment-index-number {
  flex: 0 0 34px; color: var(--text-3); font-size: 12px; font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.assignment-index-copy {
  display: flex; flex-direction: column; align-items: flex-start; gap: 4px; min-width: 0;
  padding-left: 12px; border-left: 2px solid var(--border-strong);
}
.assignment-subject-index { overflow: hidden; max-width: 100%; color: var(--primary); font-size: 11px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.assignment-index-copy strong {
  overflow: hidden; max-width: 100%; color: var(--text-strong); font-size: 15px;
  font-weight: 650; text-overflow: ellipsis; white-space: nowrap;
}
.assignment-progress-cell { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.assignment-progress-copy { display: flex; justify-content: space-between; gap: 8px; color: var(--text-2); font-size: 12px; }
.assignment-progress-copy strong { color: var(--text-strong); font-weight: 650; }
.assignment-pending-count { color: var(--primary); white-space: nowrap; }
.assignment-complete-count { color: var(--green-strong); white-space: nowrap; }
.assignment-progress-track { display: block; height: 5px; overflow: hidden; border-radius: var(--radius-pill); background: var(--border); }
.assignment-progress-track > span { display: block; height: 100%; border-radius: inherit; background: var(--primary); transition: width .2s ease; }
.assignment-progress-track.complete > span { background: var(--green); }
.assignment-latest-time { color: var(--text-3); font-size: 12px; text-align: right; white-space: nowrap; }
.assignment-row-arrow { justify-self: end; color: var(--text-3); }
.ledger-empty { padding: 34px 18px; color: var(--text-2); font-size: 14px; text-align: center; }
.verify-index-panel { margin-top: 10px; padding: 12px 18px; border: 1px solid var(--border); border-radius: var(--radius-surface); background: var(--card); }
.verify-kp-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--border); color: var(--text-2); font-size: 13px; }
.verify-kp-row:last-of-type { border-bottom: 0; }
.correction-inner-header { display: flex; align-items: flex-start; margin: 0 0 18px; }
.correction-question-row {
  width: 100%; display: grid; grid-template-columns: 42px minmax(0, 1fr) auto 20px;
  align-items: center; gap: 16px; padding: 16px 18px; border: 0; border-bottom: 1px solid var(--border);
  background: var(--card); color: var(--text); text-align: left; font: inherit; cursor: pointer;
  transition: background-color .15s ease;
}
.correction-question-row:last-of-type { border-bottom: 0; }
.correction-question-row:hover { background: color-mix(in srgb, var(--primary-50) 55%, white); }
.question-number {
  display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px;
  border: 1px solid var(--border); border-radius: var(--radius-control); background: var(--bg);
  color: var(--primary); font-size: 12px; font-weight: 700;
}
.question-row-content { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.question-row-content > strong {
  display: -webkit-box; overflow: hidden; color: var(--text-strong); font-size: 14px; font-weight: 600;
  line-height: 1.5; -webkit-box-orient: vertical; -webkit-line-clamp: 2;
}
.question-row-meta { display: flex; align-items: center; gap: 9px; min-width: 0; color: var(--text-3); font-size: 12px; }
.question-row-meta > span:not(.badge) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.question-row-meta time { margin-left: auto; white-space: nowrap; }
.question-row-status { color: var(--primary); font-size: 12px; font-weight: 600; white-space: nowrap; }
.question-row-status.complete { color: var(--green-strong); }
.load-more-corrections {
  display: block; width: 100%; padding: 13px 18px; border: 0;
  background: var(--card); color: var(--primary); font: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
}
.load-more-corrections:hover { background: var(--primary-50); }
.load-more-corrections:disabled { color: var(--text-3); cursor: wait; }
.step-text { font-size: 15px; font-weight: 600; margin-bottom: 8px; }
.detail { font-size: 14px; color: var(--text-2); }
/* v0.13.9：题目回顾完整版——原题 / 原作答（错步原地标红）/ 正确答案 / 标准过程 */
.review-block { margin-bottom: 14px; }
.review-label { display: block; font-size: 12px; font-weight: 700; color: var(--text-3); letter-spacing: .4px; margin-bottom: 5px; }
.review-stem { font-size: 16px; font-weight: 600; line-height: 1.65; }
.review-img-link { display: inline-block; margin-top: 6px; font-size: 13px; color: var(--primary); font-weight: 600; }
.orig-steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.orig-steps li { display: flex; align-items: baseline; gap: 9px; padding: 7px 10px; border-radius: var(--radius-control); background: var(--bg); font-size: 14px; }
.orig-steps li.is-error { background: var(--red-bg); box-shadow: inset 0 0 0 1.5px #DC2626; }
.orig-steps li.is-dim { opacity: .55; }
.orig-seq { flex-shrink: 0; width: 20px; height: 20px; border-radius: 50%; background: #fff; border: 1px solid var(--border); font-size: 12px; font-weight: 700; color: var(--text-2); display: inline-flex; align-items: center; justify-content: center; transform: translateY(2px); }
.orig-steps li.is-error .orig-seq { background: #DC2626; border-color: transparent; color: #fff; }
.orig-text { flex: 1; line-height: 1.55; word-break: break-word; }
.orig-flag { flex-shrink: 0; font-size: 12px; font-weight: 700; color: #DC2626; }
.note { margin-top: 8px; font-size: 14px; color: var(--text); }
.note.hint { color: var(--text-3); font-size: 13px; }
.verify-cta {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  background: var(--primary-50); border: 1px solid var(--blue-bg); border-radius: var(--radius-control);
  padding: 11px 14px; margin-top: 12px; font-size: 14px;
}
/* 页内变式题面板与验证入口（报告纯化后迁入本页） */
.verify-panel-inline { margin-top: 14px; }
.verify-done-note {
  display: flex; align-items: center; gap: 7px;
  margin-top: 12px; font-size: 14px; font-weight: 600; color: var(--green);
}
.work-bar { display: flex; flex-direction: column; align-items: flex-start; gap: 10px; margin-bottom: 16px; }
.result-actions { margin-top: 14px; }
.empty-link { color: var(--primary); font-weight: 600; }

@media (max-width: 760px) {
  .correction-ledger-head { display: none; }
  .correction-assignment-row {
    grid-template-columns: minmax(0, 1fr) 20px;
    grid-template-areas: "assignment arrow" "progress date";
    gap: 10px 12px; padding: 14px;
  }
  .assignment-index-cell { grid-area: assignment; }
  .assignment-progress-cell { grid-area: progress; padding-left: 47px; }
  .assignment-latest-time { grid-area: date; font-size: 11px; }
  .assignment-row-arrow { grid-area: arrow; }
  .correction-question-row { grid-template-columns: 38px minmax(0, 1fr) 18px; gap: 10px; padding: 14px; }
  .question-row-status { grid-column: 2; justify-self: start; grid-row: 2; }
  .question-row-meta time { display: none; }
  .question-row-content { grid-column: 2; grid-row: 1; }
  .correction-question-row > .assignment-row-arrow { grid-column: 3; grid-row: 1; }
}
@media (max-width: 480px) {
  .correction-index-toolbar { align-items: flex-start; }
  .correction-status-tabs { gap: 14px; }
  .correction-status-tabs button { font-size: 13px; }
  .verify-index-action { min-height: 34px; padding: 5px 8px; font-size: 12px; }
  .assignment-progress-copy { font-size: 11px; }
  .assignment-index-copy strong { font-size: 14px; }
  .question-row-meta { gap: 6px; }
}
</style>
