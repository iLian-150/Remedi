<!-- 学生端订正：先读取轻量作业目录，进入作业后以便利贴墙浏览错题；订正判定、
     已订正详情、变式验证沿用既有流程。右侧订正日历通过 store.correctionsDateFilter
     同步筛选目录和错题。 -->
<template>
  <div class="page">
    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载错题中…</div>

    <template v-else>
      <!-- 日期筛选状态栏（v0.9.1）：右侧栏订正日历选中某天时出现，与作业列表页同构 -->
      <div v-if="selectedDate" class="card filter-bar">
        <div class="filter-info">
          <span class="filter-title">正在看 {{ selectedDateLabel }} 的订正</span>
          <span class="filter-progress-text tnum">共 {{ correctionTotals.total }} 道题 · 待订正 {{ correctionTotals.pending }} 道题</span>
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
              :aria-label="`${assignment.assignment_title}，已订正 ${assignment.total_count - assignment.pending_count} / ${assignment.total_count} 道题，进入错题列表`"
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
        <CorrectionStickyWall
          :notes="mistakes"
          :total-count="selectedAssignmentSummary?.total_count ?? mistakes.length"
          :has-more="hasMoreMistakes"
          :loading-more="loadingMoreMistakes"
          @open="openError"
          @show-more="loadMoreCorrectionWall"
        />
      </template>

      <template v-else-if="view === 'work' && selectedError">
        <div class="work-bar">
          <button class="back-link" @click="backToQuestions">
            <AppIcon name="chevron-left" :size="16" /> 返回作业错题
          </button>
        </div>
        <section class="question-prompt-sticky" aria-label="原题">
          <div class="question-prompt-card">
            <div class="question-prompt-copy">
              <p v-if="selectedQuestionGroupStem" class="question-prompt-context">{{ selectedQuestionGroupStem }}</p>
              <p class="question-prompt-stem">{{ selectedError.question_stem || '题目内容暂未记录' }}</p>
            </div>
            <a
              v-if="selectedError.image_url"
              class="question-prompt-image"
              :href="imageHref(selectedError.image_url)"
              target="_blank"
              rel="noreferrer"
              aria-label="打开作业原图"
            >
              <img :src="imageHref(selectedError.image_url)" alt="作业原图" loading="lazy" decoding="async" />
            </a>
          </div>
        </section>
        <div class="card">
          <h3>我当时的作答</h3>
          <!-- v0.13.9：原来这里只有出错的一步、看不到原题——改成完整回顾：
               原来的题目 → 我当时的作答（错步在原步骤里原地标出）→ 解析。
               v0.13.10：正确答案与标准解题过程不在订正前直接给出（用户口径），
               先自己想、自己改，判定结果会告诉你对不对 -->
          <div class="review-block">
            <div
              v-if="origStepsLoading"
              class="correction-assessment"
              aria-live="polite"
            >
              正在汇总步骤判定…
            </div>
            <div
              v-else-if="redoRecommendation.message"
              class="correction-assessment"
              :class="{ 'is-forced-redo': redoRecommendation.forceFullRedo }"
              aria-live="polite"
            >
              {{ redoRecommendation.message }}
            </div>
            <ol v-if="origSteps.length" class="orig-steps">
              <li v-for="st in origSteps" :key="st.seq" :class="origStepClass(st)">
                <div class="orig-step-content">
                  <span class="orig-seq">{{ st.seq }}</span>
                  <span class="orig-text">{{ st.text }}</span>
                  <span v-if="errorsForStep(st.seq).length" class="orig-step-tags">
                    <ErrorTypeBadge v-for="errorDetail in errorsForStep(st.seq)" :key="errorDetail.id" :type="errorDetail.error_type" />
                    <span class="orig-flag">错误步骤</span>
                  </span>
                </div>
                <div v-if="!redoMode && !redoRecommendation.forceFullRedo && errorsForStep(st.seq).length" class="step-correction-editor">
                  <input v-model="stepCorrectionDrafts[st.seq]" type="text" :aria-label="`订正第 ${st.seq} 步`" />
                  <button class="btn small" type="button" :disabled="submitting || !stepCorrectionDrafts[st.seq]?.trim() || stepIsCorrected(st.seq)" @click="submitStepCorrection(st.seq)">
                    {{ stepIsCorrected(st.seq) ? '这一步已订正' : submittingStepSeq === st.seq ? '判定中…' : '提交这一步' }}
                  </button>
                </div>
              </li>
            </ol>
            <ol v-else-if="fallbackWrongSteps.length" class="orig-steps">
              <li v-for="detail in fallbackWrongSteps" :key="detail.seq" class="is-error">
                <div class="orig-step-content">
                  <span class="orig-seq">{{ detail.seq }}</span>
                  <span class="orig-text">{{ detail.text }}</span>
                  <span class="orig-step-tags">
                    <ErrorTypeBadge v-for="errorDetail in errorsForStep(detail.seq)" :key="errorDetail.id" :type="errorDetail.error_type" />
                    <span class="orig-flag">错误步骤</span>
                  </span>
                </div>
                <div v-if="!origStepsLoading && !redoMode && !redoRecommendation.forceFullRedo" class="step-correction-editor">
                  <input v-model="stepCorrectionDrafts[detail.seq]" type="text" :aria-label="`订正第 ${detail.seq} 步`" />
                  <button class="btn small" type="button" :disabled="submitting || !stepCorrectionDrafts[detail.seq]?.trim() || stepIsCorrected(detail.seq)" @click="submitStepCorrection(detail.seq)">
                    {{ stepIsCorrected(detail.seq) ? '这一步已订正' : submittingStepSeq === detail.seq ? '判定中…' : '提交这一步' }}
                  </button>
                </div>
              </li>
            </ol>
            <p v-else-if="selectedError.step_text" class="step-text">第 {{ selectedError.step_seq ?? '?' }} 步：{{ selectedError.step_text }}（这一步出错了）</p>
            <p v-else class="detail">原来的作答步骤暂未记录。</p>
          </div>
          <p class="detail"><strong>解析：</strong>{{ sanitizeStudentCopy(selectedError.detail ?? '') }}</p>
          <p class="correction-error-types">
            <ErrorTypeBadge v-for="errorType in selectedError.error_types" :key="errorType" :type="errorType" />
            <span class="badge badge-blue">{{ subjectName(selectedError.question_subject) }}</span>
            <span class="badge badge-blue">{{ selectedError.knowledge_point }}</span>
            <span v-if="selectedError.corrected" class="badge badge-green">已订正</span>
            <span v-else-if="selectedError.is_stubborn" class="badge badge-amber">需要加固</span>
          </p>
          <div v-if="!origStepsLoading && !redoRecommendation.forceFullRedo" class="correction-mode-switch" role="group" aria-label="订正方式">
            <button type="button" :class="{ active: !redoMode }" :aria-pressed="!redoMode" @click="startStepCorrection">修改错误步骤</button>
            <button type="button" :class="{ active: redoMode }" :aria-pressed="redoMode" @click="startFullRedo">重新做整题</button>
          </div>
        </div>

        <section v-if="redoMode" class="card redo-panel">
          <header class="redo-panel-heading">
            <span class="redo-panel-icon"><AppIcon name="edit" :size="18" /></span>
            <h3>重新做整题</h3>
          </header>
          <div class="redo-panel-editor">
            <textarea
              id="question-redo-content"
              v-model="redoContent"
              rows="8"
              aria-label="完整作答"
              placeholder="按步骤写出完整解题过程"
            />
          </div>
          <footer class="redo-panel-footer">
            <button class="btn" :disabled="submitting || !redoContent.trim()" @click="submitFullRedo">
              {{ submitting ? '判定中…' : '提交整题重做' }}
            </button>
          </footer>
        </section>

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
  QuestionRedoResult,
  StepDiagnosis,
  StudentCorrectionAssignmentSummary,
  StudentCorrectionWallItem,
} from '../../api/types'
import { sanitizeStudentCopy } from '../../utils/errorType'
import { getSubjectLabel } from '../../utils/subjectLabels'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import AppIcon from '../../components/icons/AppIcon.vue'
import CorrectionStickyWall from '../../components/CorrectionStickyWall.vue'
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
const redoContent = ref('')
const result = ref<CorrectionResult | QuestionRedoResult | null>(null)
const loading = ref(false)
const submitting = ref(false)
const submittingStepSeq = ref<number | null>(null)
const redoMode = ref(false)
const origStepsLoading = ref(false)
const stepCorrectionDrafts = reactive<Record<number, string>>({})
const error = ref('')
const QUESTION_REDO_ERROR_RATE_THRESHOLD = 0.5

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

const selectedDateLabel = computed(() => {
  if (!selectedDate.value) return ''
  const [y, m, d] = selectedDate.value.split('-')
  return `${y} 年 ${Number(m)} 月 ${Number(d)} 日`
})

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
      for (const item of mistakes.value) indexMistake(item)
      // 首屏可能额外包含深链错题，按时间恢复顺序；后续页由联合游标保证顺序。
      mistakes.value.sort((a, b) =>
        b.created_at.localeCompare(a.created_at) || b.id - a.id,
      )
    } else {
      for (const item of page.items) {
        if (loadedMistakesById.has(item.id)) continue
        mistakes.value.push(item)
        const loadedItem = mistakes.value[mistakes.value.length - 1]
        indexMistake(loadedItem)
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

function indexMistake(item: StudentCorrectionWallItem) {
  loadedMistakesById.set(item.id, item)
  for (const errorDetail of item.error_details) {
    loadedMistakesById.set(errorDetail.id, item)
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
const selectedQuestionGroupStem = computed(() => {
  const groupStem = selectedError.value?.question_group_stem?.trim() ?? ''
  const questionStem = selectedError.value?.question_stem?.trim() ?? ''
  return groupStem && !questionStem.includes(groupStem) ? groupStem : ''
})
interface FallbackWrongStep { seq: number; text: string }
const fallbackWrongSteps = computed(() => {
  const byStep = new Map<number, FallbackWrongStep>()
  for (const detail of selectedError.value?.error_details ?? []) {
    if (detail.step_seq !== null && detail.step_text && !byStep.has(detail.step_seq)) {
      byStep.set(detail.step_seq, { seq: detail.step_seq, text: detail.step_text })
    }
  }
  return Array.from(byStep.values()).sort((left, right) => left.seq - right.seq)
})
function subjectName(subject: string) { return getSubjectLabel(subject, subject || '其他学科') }

// v0.13.9：题目回顾要展示「我当时的作答」全文——错题条目里只有出错的那一步，
// 完整原步骤在提交详情里（每步带判定状态），选中错题时按 submission_id 拉一次；
// 拉不到就降级为只显示出错步骤（模板里的 v-else 分支）
const origSteps = ref<StepDiagnosis[]>([])
const origStepsSubmissionId = ref<number | null>(null)
let origLoadToken = 0
const origStepsBySubmission = new Map<number, Promise<StepDiagnosis[]>>()
const unrelatedAnswerPattern = /答非所问|偏题|跑题|脱离题目|偏离题意|与题目无关|与题意无关|和题目无关|和题意无关|答案无关|无关内容|未回答题目/
const redoRecommendation = computed(() => {
  const stepsMatchSelection = origStepsSubmissionId.value === selectedError.value?.submission_id
  const answerSteps = stepsMatchSelection
    ? origSteps.value.filter((step) => step.text.trim())
    : []
  const incorrectSeqs = new Set(
    answerSteps
      .filter((step) => step.status === 'error'
        || step.status === 'unparseable'
        || errorsForStep(step.seq).length > 0)
      .map((step) => step.seq),
  )
  const errorCount = incorrectSeqs.size
  const totalCount = answerSteps.length
  const errorRate = totalCount ? errorCount / totalCount : 0
  const diagnosisText = [
    selectedError.value?.detail,
    ...(selectedError.value?.error_details ?? []).map((detail) => detail.detail),
  ].filter(Boolean).join(' ')
  const unrelatedEvidence = diagnosisText.replace(
    /(?:并非|并不是|不是|并未|并不|没有|未曾|未|不)\s*(?:明显)?(?:存在)?(?:答非所问|偏题|跑题|脱离题目|偏离题意|与题目无关|与题意无关|和题目无关|和题意无关|答案无关|无关内容)/g,
    '',
  )
  const answerIsUnrelated = unrelatedAnswerPattern.test(unrelatedEvidence)
  const allWrong = totalCount > 0 && errorCount === totalCount
  const overThreshold = totalCount > 0 && errorRate > QUESTION_REDO_ERROR_RATE_THRESHOLD
  const forceFullRedo = answerIsUnrelated || allWrong || overThreshold

  let message = ''
  if (answerIsUnrelated) {
    message = '现有诊断标记作答与题目无关，请重新做整题。'
  } else if (allWrong) {
    message = `整题 ${errorCount} 步均判错，请重新做整题。`
  } else if (overThreshold) {
    const thresholdPercent = Math.round(QUESTION_REDO_ERROR_RATE_THRESHOLD * 100)
    message = `错误率 ${Math.round(errorRate * 100)}%（超过 ${thresholdPercent}%），请重新做整题。`
  } else if (totalCount > 0) {
    const thresholdPercent = Math.round(QUESTION_REDO_ERROR_RATE_THRESHOLD * 100)
    message = `当前错误率 ${Math.round(errorRate * 100)}%；超过 ${thresholdPercent}% 时优先重新做整题。`
  }

  return { errorCount, totalCount, errorRate, answerIsUnrelated, allWrong, overThreshold, forceFullRedo, message }
})
watch(redoRecommendation, (recommendation) => {
  if (recommendation.forceFullRedo && !redoMode.value) startFullRedo()
})

async function loadOrigSteps() {
  const err = selectedError.value
  const token = ++origLoadToken
  origSteps.value = []
  origStepsSubmissionId.value = null
  origStepsLoading.value = Boolean(err)
  if (!err) return
  const submissionId = err.submission_id
  for (const detail of err.error_details) {
    if (detail.step_seq !== null && detail.step_text && stepCorrectionDrafts[detail.step_seq] === undefined) {
      stepCorrectionDrafts[detail.step_seq] = detail.step_text
    }
  }
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
    origStepsSubmissionId.value = submissionId
    for (const step of steps) {
      if (errorsForStep(step.seq).length) stepCorrectionDrafts[step.seq] = step.text
    }
    origStepsLoading.value = false
  } catch {
    if (origStepsBySubmission.get(submissionId) === stepsRequest) {
      origStepsBySubmission.delete(submissionId)
    }
    if (token === origLoadToken) {
      origSteps.value = []
      origStepsLoading.value = false
    }
  }
}
watch(selectedError, () => { void loadOrigSteps() }, { flush: 'sync' })

function origStepClass(st: StepDiagnosis) {
  return {
    'is-error': errorsForStep(st.seq).length > 0 || st.status === 'error',
    'is-dim': st.status === 'skipped' || st.status === 'unparseable'
  }
}

function errorsForStep(stepSeq: number) {
  return selectedError.value?.error_details.filter((item) => item.step_seq === stepSeq) ?? []
}

function stepIsCorrected(stepSeq: number): boolean {
  const errors = errorsForStep(stepSeq)
  return errors.length > 0 && errors.every((item) => item.corrected)
}

function startFullRedo() {
  redoMode.value = true
  redoContent.value = ''
  result.value = null
}

function startStepCorrection() {
  if (redoRecommendation.value.forceFullRedo) return
  redoMode.value = false
  result.value = null
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
  redoContent.value = ''
  redoMode.value = false
  for (const key of Object.keys(stepCorrectionDrafts)) delete stepCorrectionDrafts[Number(key)]
  result.value = null
  justVerified.value = false
  verifyTarget.value = null
}

function updateQuestionCorrectionStatus(item: StudentCorrectionWallItem, completedByRedo = false) {
  if (completedByRedo) {
    item.error_details.forEach((detail) => { detail.corrected = true })
  }
  const nowCorrected = completedByRedo || (
    item.error_details.length > 0 && item.error_details.every((detail) => detail.corrected)
  )
  if (nowCorrected && !item.corrected) {
    item.corrected = true
    const summary = assignmentSummaries.value.find((entry) => entry.assignment_id === item.assignment_id)
    if (summary) summary.pending_count = Math.max(0, summary.pending_count - 1)
  }
}

async function submitStepCorrection(stepSeq: number) {
  const item = selectedError.value
  const target = errorsForStep(stepSeq).find((detail) => !detail.corrected)
  const content = stepCorrectionDrafts[stepSeq]?.trim() ?? ''
  if (!item || !target || !content) return
  submitting.value = true
  submittingStepSeq.value = stepSeq
  error.value = ''
  result.value = null
  justVerified.value = false
  verifyTarget.value = null
  try {
    result.value = await student.submitCorrection({
      error_id: target.id,
      content,
    })
    if (result.value.is_correct === true) {
      for (const detail of item.error_details) {
        if (detail.step_seq === stepSeq) detail.corrected = true
      }
      updateQuestionCorrectionStatus(item)
    }
  } catch (e) {
    error.value = '订正提交失败：' + errDetail(e)
    console.error(e)
  } finally {
    submitting.value = false
    submittingStepSeq.value = null
  }
}

async function submitFullRedo() {
  const item = selectedError.value
  const content = redoContent.value.trim()
  if (!item || !content) return
  submitting.value = true
  error.value = ''
  result.value = null
  justVerified.value = false
  verifyTarget.value = null
  try {
    result.value = await student.submitQuestionRedo({
      submission_id: item.submission_id,
      content,
    })
    if (result.value.is_correct === true) updateQuestionCorrectionStatus(item, true)
  } catch (e) {
    error.value = '整题重做提交失败：' + errDetail(e)
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
.correction-ledger {
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
.step-text { font-size: 15px; font-weight: 600; margin-bottom: 8px; }
.detail { font-size: 14px; color: var(--text-2); }
/* v0.13.9：题目回顾完整版——原题 / 原作答（错步原地标红）/ 正确答案 / 标准过程 */
.review-block { margin-bottom: 14px; }
.correction-assessment { margin: 8px 0 10px; padding: 9px 12px; border: 1px solid var(--border); border-radius: var(--radius-control); background: var(--surface-2); color: var(--text-2); font-size: 13px; line-height: 1.5; }
.correction-assessment.is-forced-redo { border-color: var(--amber-border); background: var(--amber-bg); color: var(--amber-strong); font-weight: 600; }
.question-prompt-sticky { position: sticky; top: 12px; z-index: 120; isolation: isolate; margin-bottom: 16px; }
.question-prompt-card { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; gap: 18px; max-height: min(44vh, 440px); overflow: auto; overscroll-behavior: contain; padding: 16px 20px; border: 1px solid var(--border); border-radius: var(--radius-panel); background: var(--card); box-shadow: var(--shadow-md); }
.question-prompt-copy { min-width: 0; }
.question-prompt-context { margin: 0 0 7px; color: var(--text-2); font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
.question-prompt-stem { margin: 0; color: var(--text); font-size: 16px; font-weight: 650; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.question-prompt-image { display: block; width: min(30vw, 340px); max-height: 36vh; overflow: hidden; border: 1px solid var(--border); border-radius: var(--radius-control); background: var(--surface-2); }
.question-prompt-image img { display: block; width: 100%; max-height: 36vh; object-fit: contain; }
.orig-steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.orig-steps li { display: flex; flex-direction: column; gap: 0; padding: 12px 14px; border: 1px solid transparent; border-radius: var(--radius-control); background: var(--bg); font-size: 14px; }
.orig-steps li.is-error { border-color: var(--red-border); background: var(--red-bg); }
.orig-steps li.is-dim { opacity: .55; }
.orig-seq { flex-shrink: 0; width: 20px; height: 20px; border-radius: 50%; background: #fff; border: 1px solid var(--border); font-size: 12px; font-weight: 700; color: var(--text-2); display: inline-flex; align-items: center; justify-content: center; transform: translateY(2px); }
.orig-steps li.is-error .orig-seq { background: var(--red); border-color: transparent; color: #fff; }
.orig-step-content { display: grid; grid-template-columns: 20px minmax(0, 1fr) auto; align-items: start; gap: 10px; width: 100%; }
.orig-text { min-width: 0; line-height: 1.55; word-break: break-word; }
.orig-step-tags { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 6px; }
.orig-flag { flex-shrink: 0; padding: 3px 8px; border: 1px solid var(--red-border); border-radius: var(--radius-pill); background: var(--red-bg); color: var(--red-strong); font-size: 12px; font-weight: 650; white-space: nowrap; }
.step-correction-editor { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 10px; margin: 10px 0 0 30px; }
.step-correction-editor input { min-width: 0; min-height: 42px; }
.correction-error-types { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 10px; }
.correction-mode-switch { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.correction-mode-switch button { min-height: 36px; padding: 7px 12px; border: 1px solid var(--border); border-radius: var(--radius-control); background: var(--card); color: var(--text-2); font: inherit; font-size: 13px; font-weight: 600; cursor: pointer; }
.correction-mode-switch button.active { border-color: var(--primary); background: var(--primary-50); color: var(--primary); }
.redo-panel { border-color: var(--blue-bg); background: linear-gradient(145deg, var(--primary-50), var(--card) 48%); }
.redo-panel-heading { display: flex; align-items: center; gap: 11px; margin-bottom: 16px; }
.redo-panel-heading h3 { margin: 0; font-size: 17px; }
.redo-panel-icon { display: inline-flex; width: 38px; height: 38px; align-items: center; justify-content: center; border-radius: var(--radius-control); background: var(--blue-bg); color: var(--primary); }
.redo-panel-editor textarea { display: block; width: 100%; min-height: 210px; padding: 14px 16px; border-color: var(--border); border-radius: var(--radius-surface); background: var(--card); font-size: 15px; line-height: 1.75; }
.redo-panel-footer { display: flex; justify-content: flex-end; margin-top: 14px; }
.redo-panel-footer .btn { min-width: 150px; }
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

@media (max-width: 960px) {
  .question-prompt-sticky { top: 60px; }
}
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
}
@media (max-width: 480px) {
  .correction-index-toolbar { align-items: flex-start; }
  .correction-status-tabs { gap: 14px; }
  .correction-status-tabs button { font-size: 13px; }
  .verify-index-action { min-height: 34px; padding: 5px 8px; font-size: 12px; }
  .assignment-progress-copy { font-size: 11px; }
  .assignment-index-copy strong { font-size: 14px; }
  .orig-step-content { grid-template-columns: 20px minmax(0, 1fr); }
  .orig-step-tags { grid-column: 2; justify-content: flex-start; margin-top: 3px; }
  .step-correction-editor { grid-template-columns: minmax(0, 1fr); margin-left: 30px; }
  .step-correction-editor .btn { width: 100%; }
  .redo-panel { padding: 16px; }
  .redo-panel-editor textarea { min-height: 180px; }
  .redo-panel-footer .btn { width: 100%; }
  .question-prompt-card { grid-template-columns: minmax(0, 1fr); gap: 10px; max-height: 48vh; padding: 13px 15px; }
  .question-prompt-stem { font-size: 14px; }
  .question-prompt-image { width: min(100%, 360px); max-height: 20vh; }
  .question-prompt-image img { max-height: 20vh; }
}
</style>
