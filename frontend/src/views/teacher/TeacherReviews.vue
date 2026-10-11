<!-- 教师端：待审核（v0.9.0 新增）——低置信度错因由老师复核，通过后学生才看得到诊断。
     作业列表保持为背景页，点击作业直接打开审核窗口；学生和题目在窗口左侧切换，
     右侧显示答题情况（过程提示/分步诊断/错因复核/
     AI 评分/最终分与通过）。逐条错因可先一键纠错再通过（改后通过）；
     通过后后端给学生发 review_approved 提醒。页顶可一键全部通过。
     v0.13.12 顺带修掉「改分后点通过没反应」：最终分输入框 type=number 时
     Vue 会把 v-model 值自动转成数字，approveSelected 里对它调 .trim() 直接
     抛错、 handler 静默死掉——改用文本输入 + String() 归一化后不再复现。
     接口：4.23 待审队列 / 4.24 审核详情 / 4.25 通过 / 4.26 全部通过 / 4.2 一键纠错。 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>待审核</h2>
      <p class="page-sub">本次作答正确率或错因置信度低于 60% 的记录会进入这里复核；点击作业打开审核窗口，在窗口中切换学生和题目，确认无误后点「通过」。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="okMsg" class="ok-msg">{{ okMsg }}</div>
    <div v-if="loading" class="loading">加载待审核队列中…</div>

    <template v-else>
      <div class="card queue-head">
        <span class="queue-count">
          待审核 <b class="tnum">{{ items.length }}</b> 份 · 来自 <b class="tnum">{{ assignmentGroups.length }}</b> 份作业
        </span>
        <button class="btn small" :disabled="!items.length || approvingAll" @click="approveAll">
          {{ approvingAll ? '处理中…' : '全部通过' }}
        </button>
      </div>

      <div v-if="!items.length" class="card">
        <div class="empty">太好了，没有待审核的提交，AI 批改的结果都已经放行给学生了。</div>
      </div>

      <div v-else class="assign-list">
        <button
          v-for="g in assignmentGroups"
          :key="String(g.id)"
          type="button"
          class="card assign-card"
          @click="enterAssignment(g)"
        >
          <span class="assign-card-thumb">
            <img v-if="g.imageUrl" :src="imageSrc(g.imageUrl)" :alt="`${g.title}作业原图`" loading="lazy" />
            <span v-else class="assign-card-thumb-empty">暂无作业图片</span>
          </span>
          <span class="assign-card-main">
            <span class="assign-card-text">
              <span class="assign-card-title">{{ g.title }}</span>
              <span class="assign-card-question">
                <b>题目</b>
                <span>{{ g.questionStems[0] || '暂无题目文本' }}</span>
                <small v-if="g.questionIds.length > 1">另有 {{ g.questionIds.length - 1 }} 道题</small>
              </span>
              <span class="assign-card-meta">
                <span class="tnum">{{ g.students.length }}</span> 名学生 ·
                待审核 <span class="tnum">{{ g.total }}</span> 份 ·
                <span v-if="g.errorItems" class="meta-bad">有问题 {{ g.errorItems }} 份</span>
                <span v-if="g.total - g.errorItems" class="meta-good">全对 {{ g.total - g.errorItems }} 份</span>
              </span>
              <span class="assign-card-time">最近提交 {{ fmtTime(g.latest) }}</span>
            </span>
            <span class="assign-card-accuracy" :class="accuracyClass(g)">
              <span class="accuracy-label">待审步骤正确率</span>
              <strong>{{ accuracyPercent(g) ?? '—' }}<small v-if="accuracyPercent(g) !== null">%</small></strong>
              <span class="accuracy-steps" v-if="g.totalAnswerSteps">
                {{ g.correctSteps }} / {{ g.totalAnswerSteps }} 步正确
              </span>
              <span class="accuracy-steps" v-else>暂无有效作答步骤</span>
            </span>
          </span>
          <AppIcon name="chevron-right" :size="18" class="queue-row-arrow" />
        </button>
      </div>

      <div v-if="modalOpen" class="review-modal-mask" @click.self="closeReviewModal">
        <section class="review-modal" role="dialog" aria-modal="true" aria-labelledby="review-modal-title">
          <header class="review-modal-header">
            <div class="review-modal-brand">
              <span class="review-modal-mark"><BrandLogo :size="23" /></span>
              <strong>Remedi</strong>
              <span id="review-modal-title" class="review-modal-title">原题与解题过程</span>
              <span class="review-modal-meta">
                {{ currentAssignment?.title }}<template v-if="detail"> · {{ detail.student.name }} · {{ fmtTime(detail.submitted_at) }}</template>
              </span>
            </div>
            <button type="button" class="review-modal-close" aria-label="关闭" @click="closeReviewModal">×</button>
          </header>

          <div class="review-modal-body">
            <aside class="review-modal-nav">
              <p class="side-title">本作业的学生（{{ currentAssignment?.students.length ?? 0 }}）</p>
              <div v-for="sg in currentAssignment?.students ?? []" :key="sg.student.id" class="review-modal-nav-group">
                <button
                  type="button"
                  class="queue-row"
                  :class="{ active: sg.student.id === selectedStudentId }"
                  @click="selectStudent(sg.student.id)"
                >
                  <span class="student-avatar small">{{ sg.student.name.slice(0, 1) }}</span>
                  <span class="queue-row-main">
                    <span class="queue-row-top">
                      <strong>{{ sg.student.name }}</strong>
                      <span class="badge badge-amber tnum">待审核 {{ sg.items.length }}</span>
                    </span>
                    <span class="queue-row-meta">
                      <span>学号 {{ sg.student.student_no }}</span>
                      <span v-if="sg.items.some((i) => i.error_count)" class="meta-bad">有错题</span>
                      <span v-else class="meta-good">全对</span>
                    </span>
                  </span>
                </button>
                <div v-if="sg.student.id === selectedStudentId" class="student-questions">
                  <button
                    v-for="it in sg.items"
                    :key="it.submission_id"
                    type="button"
                    class="sq-row"
                    :class="{ active: it.submission_id === selectedId }"
                    @click="selectItem(it.submission_id)"
                  >
                    <span class="sq-stem">{{ it.question_stem }}</span>
                    <span class="sq-badges">
                      <span class="badge badge-blue">{{ it.knowledge_point }}</span>
                      <span v-if="it.error_count" class="badge badge-red tnum">{{ it.error_count }} 处问题</span>
                      <span v-else class="badge badge-green">全对</span>
                    </span>
                  </button>
                </div>
              </div>
            </aside>

            <div v-if="detailLoading" class="review-modal-loading">
              <span class="loading">加载诊断中…</span>
            </div>
            <div v-else-if="detail" class="review-modal-content">
              <div class="review-modal-left">
                <section class="review-modal-panel">
                  <div class="review-panel-heading">
                    <h3>上传的原图</h3>
                    <span>{{ currentReviewItem?.image_name || '作业原图' }}</span>
                  </div>
                  <a
                    v-if="currentReviewItem?.image_url"
                    class="review-original-image-link"
                    :href="imageSrc(currentReviewItem.image_url)"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <img :src="imageSrc(currentReviewItem.image_url)" :alt="currentReviewItem.image_name || '学生作答原图'" />
                  </a>
                  <div v-else class="review-image-empty">当前提交没有可显示的作答原图。</div>
                </section>

                <section class="review-modal-panel">
                  <div class="review-panel-heading">
                    <h3>图片中的文字</h3>
                    <span>识别题目，供审核对照</span>
                  </div>
                  <div class="review-question-text">{{ detail.question.stem }}</div>
                </section>
              </div>

              <div class="review-modal-right">
                <section class="review-modal-panel">
                  <div class="review-panel-heading">
                    <h3>解题过程</h3>
                    <span>{{ reviewAnswerSteps.length }} 步</span>
                  </div>
                  <div v-if="detail.process_check?.suspicious" class="review-process-note">
                    <strong>过程提示</strong>
                    <p v-for="s in detail.process_check.signals" :key="s.code">{{ s.text }}</p>
                    <small v-if="detail.process_check.final_answer || detail.process_check.reference_answer">
                      学生答案：{{ detail.process_check.final_answer ?? '—' }} · 参考答案：{{ detail.process_check.reference_answer ?? '—' }}
                    </small>
                  </div>
                  <div class="review-solution-steps">
                    <article
                      v-for="st in reviewAnswerSteps"
                      :key="st.seq"
                      class="review-solution-step"
                      :class="{ 'is-error': st.status === 'error', 'is-correct': st.status === 'ok' }"
                    >
                      <div class="review-solution-step-head">
                        <strong>第 {{ st.seq }} 步</strong>
                        <span>{{ STEP_STATUS_TEXT[st.status] }}</span>
                      </div>
                      <p>{{ st.text }}</p>
                    </article>
                    <p v-if="!reviewAnswerSteps.length" class="review-empty-note">这份提交没有可展示的分步作答。</p>
                  </div>
                  <p v-if="!detail.diagnosis.errors.length" class="ok-line">这份作答全部正确，通过后学生会看到鼓励反馈。</p>
                </section>

                <section v-if="detail.diagnosis.errors.length" class="review-modal-panel">
                  <div class="review-panel-heading">
                    <h3>需要修改的地方</h3>
                    <span>{{ detail.diagnosis.errors.length }} 处</span>
                  </div>
                  <p class="review-panel-note">分类不对的先在这里修改；保存后再通过，学生收到的是修正后的诊断。</p>
                  <div v-for="e in detail.diagnosis.errors" :key="e.id" class="review-error">
                    <div class="review-error-head">
                      <span>第 {{ e.step_seq ?? '—' }} 步</span>
                      <ErrorTypeBadge :type="e.error_type" />
                      <span class="conf-text tnum">置信度 {{ Math.round(e.confidence * 100) }}%</span>
                    </div>
                    <p class="detail-text">{{ e.detail }}</p>
                    <p v-if="e.step_text" class="review-error-step">作答：{{ e.step_text }}</p>
                    <div class="correct-row">
                      <select v-model="correctForms[e.id].type">
                        <option value="">改错因…</option>
                        <option v-for="t in ERROR_TYPES" :key="t" :value="t">{{ t }}</option>
                      </select>
                      <input v-model="correctForms[e.id].note" type="text" placeholder="备注（可选）" />
                      <button
                        class="btn small secondary"
                        :disabled="!correctForms[e.id].type || correctingId === e.id"
                        @click="saveCorrection(e.id)"
                      >
                        {{ correctingId === e.id ? '保存中…' : '保存纠错' }}
                      </button>
                    </div>
                  </div>
                </section>

                <section v-if="detail.score" class="review-modal-panel review-score-panel">
                  <h3>AI 评分</h3>
                  <p class="score-line">
                    本题满分 <b class="tnum">{{ fmtScore(detail.score.question_max) }}</b> 分 ·
                    AI 评分 <b class="tnum">{{ detail.score.ai_score !== null ? fmtScore(detail.score.ai_score) : '—' }}</b> 分
                    <span class="hint">（步骤对了 {{ detail.score.ok_steps }}/{{ detail.score.total_steps }} 步）</span>
                  </p>
                  <p v-if="detail.score.final_score !== null" class="score-line">最终分 {{ fmtScore(detail.score.final_score) }} 分（已落定）</p>
                </section>

                <section class="review-modal-panel approve-bar">
                  <div v-if="detail.review_status === 'pending' && detail.score" class="score-editor">
                    <div class="score-editor-row">
                      <label for="final-score-input">最终分</label>
                      <span class="score-input-wrap" :class="{ changed: scoreChanged }">
                        <input
                          id="final-score-input"
                          v-model="finalScoreInput"
                          type="text"
                          inputmode="decimal"
                          :placeholder="detail.score.ai_score !== null ? fmtScore(detail.score.ai_score) : 'AI 分'"
                        />
                        <span class="score-suffix">分</span>
                      </span>
                      <span class="score-max">/ 本题满分 {{ fmtScore(detail.score.question_max) }} 分</span>
                    </div>
                    <div class="score-editor-row sub">
                      <span class="hint">留空 = 用 AI 评分；填入数值则按该分数通过。</span>
                      <span class="score-quick">
                        <button type="button" class="chip-btn" :disabled="!scoreChanged" @click="finalScoreInput = ''">用 AI 评分</button>
                        <button type="button" class="chip-btn" @click="finalScoreInput = fmtScore(detail.score.question_max)">给满分</button>
                      </span>
                    </div>
                  </div>
                  <div class="approve-actions">
                    <p class="hint" style="margin: 0">通过后，学生会收到提醒并能查看诊断与错题。</p>
                    <button class="btn" :disabled="approving" @click="approveSelected">
                      {{ approving ? '通过中…' : '通过审核' }}
                    </button>
                  </div>
                </section>
              </div>
            </div>
            <div v-else class="review-modal-loading">
              <span class="error-msg">{{ error || '审核详情暂时无法加载。' }}</span>
            </div>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useTeacherStore } from '../../stores/teacher'
import type { ReviewDetail, ReviewPendingItem } from '../../api/types'
import { ERROR_TYPES, STEP_STATUS_TEXT } from '../../api/types'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import AppIcon from '../../components/icons/AppIcon.vue'
import BrandLogo from '../../components/BrandLogo.vue'

const teacher = useTeacherStore()
const route = useRoute()

const items = ref<ReviewPendingItem[]>([])
const selectedId = ref<number | null>(null)
const detail = ref<ReviewDetail | null>(null)
const modalOpen = ref(false)
const loading = ref(false)
const detailLoading = ref(false)
const approving = ref(false)
const approvingAll = ref(false)
const correctingId = ref<number | null>(null)
const error = ref('')
const okMsg = ref('')
let reviewRefreshTimer: number | undefined
let reviewRefreshInFlight = false
/** 每条错因一份纠错表单（type/note），按 error_id 索引 */
const correctForms = reactive<Record<number, { type: string; note: string }>>({})

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

function imageSrc(path: string): string {
  if (/^https?:\/\//i.test(path)) return path
  const base = String(import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
  return `${base}${path.startsWith('/') ? path : `/${path}`}`
}

function fmtScore(v: number): string {
  return String(Math.round(v * 10) / 10)
}

/** 评分系统：老师改分输入（始终按字符串处理，留空 = 用 AI 评分通过）。
 * 注意：输入框用 type=text——type=number 时 Vue 会把 v-model 转成数字，
 * 曾导致 approveSelected 里 .trim() 抛错、点通过毫无反应（v0.13.12 修）。 */
const finalScoreInput = ref('')
const scoreChanged = computed(() => String(finalScoreInput.value ?? '').trim() !== '')

function errDetail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof d === 'string' ? d : '请稍后重试。'
}

// ---------- 按作业、按学生分组 ----------

type StudentOfItem = ReviewPendingItem['student']
interface StudentGroup { student: StudentOfItem; items: ReviewPendingItem[] }
interface AssignmentGroup {
  id: number | null
  title: string
  students: StudentGroup[]
  total: number
  errorItems: number
  correctSteps: number
  totalAnswerSteps: number
  questionIds: number[]
  questionStems: string[]
  latest: string
  imageUrl: string | null
}

const assignmentGroups = computed<AssignmentGroup[]>(() => {
  const map = new Map<string, AssignmentGroup>()
  for (const it of items.value) {
    const key = String(it.assignment_id)
    let g = map.get(key)
    if (!g) {
      g = {
        id: it.assignment_id,
        title: it.assignment_title || '未命名作业',
        students: [],
        total: 0,
        errorItems: 0,
        correctSteps: 0,
        totalAnswerSteps: 0,
        questionIds: [],
        questionStems: [],
        latest: '',
        imageUrl: null
      }
      map.set(key, g)
    }
    let sg = g.students.find((s) => s.student.id === it.student.id)
    if (!sg) {
      sg = { student: it.student, items: [] }
      g.students.push(sg)
    }
    sg.items.push(it)
    g.total += 1
    if (it.error_count) g.errorItems += 1
    g.correctSteps += it.correct_steps ?? 0
    g.totalAnswerSteps += it.total_steps ?? 0
    if (!g.questionIds.includes(it.question_id)) {
      g.questionIds.push(it.question_id)
      if (it.question_stem.trim()) g.questionStems.push(it.question_stem.trim())
    }
    if (it.submitted_at > g.latest) g.latest = it.submitted_at
    if (!g.imageUrl && it.image_url) g.imageUrl = it.image_url
  }
  return [...map.values()]
})

function accuracyPercent(group: AssignmentGroup): number | null {
  return group.totalAnswerSteps > 0
    ? Math.round(group.correctSteps / group.totalAnswerSteps * 100)
    : null
}

function accuracyClass(group: AssignmentGroup): string {
  const rate = accuracyPercent(group)
  if (rate === null) return 'accuracy-no-data'
  if (rate < 60) return 'accuracy-low'
  if (rate < 80) return 'accuracy-mid'
  return 'accuracy-high'
}

/** 当前审核窗口对应的作业 id（字符串键，与分组口径一致） */
const viewAssignmentId = ref<string | null>(null)
const selectedStudentId = ref<number | null>(null)

const currentAssignment = computed(() =>
  assignmentGroups.value.find((g) => String(g.id) === viewAssignmentId.value) ?? null
)
const currentReviewItem = computed(() =>
  items.value.find((i) => i.submission_id === selectedId.value) ?? null
)
const reviewAnswerSteps = computed(() =>
  detail.value?.diagnosis.steps.filter((step) => step.status !== 'stem') ?? []
)

function closeReviewModal() {
  modalOpen.value = false
  viewAssignmentId.value = null
  selectedStudentId.value = null
  selectedId.value = null
  detail.value = null
}

function handleReviewModalKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && modalOpen.value) closeReviewModal()
}

function enterAssignment(g: AssignmentGroup) {
  viewAssignmentId.value = String(g.id)
  const first = g.students.find((student) => student.items.length > 0)
  if (first) {
    selectedStudentId.value = first.student.id
    void selectItem(first.items[0].submission_id)
  }
}

function selectStudent(studentId: number) {
  selectedStudentId.value = studentId
  const sg = currentAssignment.value?.students.find((s) => s.student.id === studentId)
  if (sg?.items.length) void selectItem(sg.items[0].submission_id)
}

/** 审核通过后仍留在窗口，自动打开同作业下一份，再到下一作业。 */
async function relocateAfterApprove(assignmentKey: string | null, studentId: number | null) {
  const groups = assignmentGroups.value
  const g = groups.find((x) => String(x.id) === assignmentKey) ?? groups[0]
  const sg = g?.students.find((s) => s.student.id === studentId) ?? g?.students[0]
  if (g && sg) {
    viewAssignmentId.value = String(g.id)
    selectedStudentId.value = sg.student.id
    await selectItem(sg.items[0].submission_id)
    return
  }
  closeReviewModal()
}

// ---------- 队列与详情 ----------

async function loadQueue(preselect?: number) {
  loading.value = true
  error.value = ''
  try {
    items.value = await teacher.fetchPendingReviews()
    if (preselect) {
      const target = items.value.find((i) => i.submission_id === preselect)
      if (target) {
        viewAssignmentId.value = String(target.assignment_id)
        selectedStudentId.value = target.student.id
        await selectItem(target.submission_id)
        return
      }
    }
    viewAssignmentId.value = null
    selectedStudentId.value = null
    selectedId.value = null
    detail.value = null
  } catch (e) {
    error.value = '待审核队列加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
}

/** 学生可能在老师已打开审核页后才提交；定时刷新队列，保留当前窗口和选择。 */
async function refreshQueueSilently() {
  if (reviewRefreshInFlight || loading.value || document.visibilityState === 'hidden') return
  reviewRefreshInFlight = true
  const currentId = selectedId.value
  try {
    items.value = await teacher.fetchPendingReviews()
    if (currentId && selectedId.value === currentId
      && !items.value.some((item) => item.submission_id === currentId)) {
      closeReviewModal()
      okMsg.value = '审核队列已更新，当前作答已不在待审核列表中。'
    }
  } catch (e) {
    // 后台刷新失败时保留当前队列；页面首次加载仍由 loadQueue 展示错误。
    console.error('待审核队列自动刷新失败', e)
  } finally {
    reviewRefreshInFlight = false
  }
}

function onReviewPageFocus() {
  void refreshQueueSilently()
}

function onReviewPageVisibilityChange() {
  if (document.visibilityState === 'visible') void refreshQueueSilently()
}

async function selectItem(submissionId: number) {
  selectedId.value = submissionId
  modalOpen.value = true
  detailLoading.value = true
  detail.value = null
  error.value = ''
  finalScoreInput.value = ''
  try {
    const d = await teacher.fetchReviewDetail(submissionId)
    detail.value = d
    d.diagnosis.errors.forEach((e) => {
      if (!correctForms[e.id]) correctForms[e.id] = { type: '', note: '' }
    })
  } catch (e) {
    error.value = '审核详情加载失败：' + errDetail(e)
    console.error(e)
  } finally {
    detailLoading.value = false
  }
}

async function saveCorrection(errorId: number) {
  const form = correctForms[errorId]
  if (!form?.type) return
  correctingId.value = errorId
  error.value = ''
  try {
    await teacher.correctError(errorId, {
      error_type: form.type,
      teacher_note: form.note.trim() || undefined
    })
    form.type = ''
    form.note = ''
    okMsg.value = '错因已修改并回标入库，点「通过审核」后学生才会看到。'
    if (selectedId.value) await selectItem(selectedId.value)
  } catch (e) {
    error.value = '纠错保存失败：' + errDetail(e)
    console.error(e)
  } finally {
    correctingId.value = null
  }
}

async function approveSelected() {
  if (!selectedId.value) return
  // 评分系统：改分先做前端校验（0 ~ 本题满分），后端还会再验一遍。
  // 输入统一 String() 归一化——历史上这里对数字调 .trim() 直接抛错（见文件头）。
  let finalScore: number | undefined
  const raw = String(finalScoreInput.value ?? '').trim()
  if (raw !== '') {
    const v = Number(raw)
    const max = detail.value?.score?.question_max ?? 0
    if (Number.isNaN(v) || v < 0 || v > max) {
      error.value = `最终分要在 0 到 ${fmtScore(max)} 分之间。`
      return
    }
    finalScore = v
  }
  approving.value = true
  error.value = ''
  const approvedId = selectedId.value
  const assignmentKey = viewAssignmentId.value
  const studentId = selectedStudentId.value
  try {
    const name = detail.value?.student.name ?? ''
    await teacher.approveReview(approvedId, finalScore)
    items.value = items.value.filter((i) => i.submission_id !== approvedId)
    okMsg.value = `已通过，${name} 会收到提醒并能看到诊断了。`
    detail.value = null
    selectedId.value = null
    await relocateAfterApprove(assignmentKey, studentId)
  } catch (e) {
    error.value = '审核通过失败：' + errDetail(e)
    console.error(e)
  } finally {
    approving.value = false
  }
}

async function approveAll() {
  approvingAll.value = true
  error.value = ''
  try {
    const n = await teacher.approveAllReviews()
    items.value = []
    closeReviewModal()
    detail.value = null
    selectedId.value = null
    okMsg.value = `已全部通过 ${n} 份，学生们都会收到提醒。`
  } catch (e) {
    error.value = '全部通过失败：' + errDetail(e)
    console.error(e)
  } finally {
    approvingAll.value = false
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleReviewModalKeydown)
  window.addEventListener('focus', onReviewPageFocus)
  document.addEventListener('visibilitychange', onReviewPageVisibilityChange)
  reviewRefreshTimer = window.setInterval(() => void refreshQueueSilently(), 15000)
  const preset = Number(route.query.submission_id)
  void loadQueue(preset || undefined)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleReviewModalKeydown)
  window.removeEventListener('focus', onReviewPageFocus)
  document.removeEventListener('visibilitychange', onReviewPageVisibilityChange)
  if (reviewRefreshTimer !== undefined) window.clearInterval(reviewRefreshTimer)
})
</script>

<style scoped>
.queue-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 18px; flex-wrap: wrap; }
.queue-count { font-size: 15px; font-weight: 600; }
.queue-count b { color: var(--primary); font-size: 19px; }
/* 一级：作业卡列表 */
.assign-list { display: flex; flex-direction: column; gap: 10px; }
.assign-card {
  display: grid; grid-template-columns: minmax(140px, 19%) minmax(0, 1fr) auto;
  align-items: center; gap: 18px; text-align: left; width: 100%;
  padding: 14px 18px; cursor: pointer; font-family: inherit; margin-bottom: 0;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.assign-card:hover { border-color: #C9D6F2; }
.assign-card-thumb {
  width: 100%; height: 126px;
  display: flex; align-items: center; justify-content: center; overflow: hidden;
  border: 1px solid var(--border); border-radius: 10px; background: #F8FAFC;
}
.assign-card-thumb img { width: 100%; height: 100%; object-fit: contain; }
.assign-card-thumb-empty { color: var(--text-3); font-size: 13px; }
.assign-card-main { min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr) 148px; align-items: center; gap: 18px; }
.assign-card-text { min-width: 0; display: flex; flex-direction: column; gap: 7px; }
.assign-card-title { font-size: 16px; font-weight: 700; }
.assign-card-question { display: flex; align-items: baseline; gap: 7px; min-width: 0; color: var(--text-2); font-size: 14px; line-height: 1.55; }
.assign-card-question b { flex-shrink: 0; color: var(--text); }
.assign-card-question > span { display: -webkit-box; min-width: 0; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.assign-card-question small { flex-shrink: 0; color: var(--text-3); font-size: 12px; }
.assign-card-meta { font-size: 13px; color: var(--text-2); }
.assign-card-time { font-size: 12px; color: var(--text-3); }
.assign-card-accuracy { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 94px; padding: 9px 12px; border-radius: 12px; background: #F8FAFC; text-align: center; }
.accuracy-label { font-size: 12px; font-weight: 700; color: var(--text-2); }
.assign-card-accuracy strong { margin-top: 1px; font-size: 34px; line-height: 1.1; font-variant-numeric: tabular-nums; }
.assign-card-accuracy strong small { margin-left: 1px; font-size: 17px; }
.accuracy-steps { margin-top: 4px; color: var(--text-3); font-size: 11px; line-height: 1.35; }
.accuracy-low { background: #FFF1F0; color: #C2413A; }
.accuracy-mid { background: #FFF7E6; color: #B7791F; }
.accuracy-high { background: #ECFDF3; color: #16804A; }
.accuracy-no-data { background: #F3F4F6; color: #64748B; }
.meta-bad { color: #B91C1C; font-weight: 600; }
.meta-good { color: #15803D; font-weight: 600; }
@media (max-width: 760px) {
  .assign-card { grid-template-columns: 112px minmax(0, 1fr) auto; gap: 12px; padding: 12px; }
  .assign-card-thumb { height: 112px; }
  .assign-card-main { grid-template-columns: minmax(0, 1fr) 104px; gap: 10px; }
  .assign-card-accuracy { min-height: 84px; padding: 7px; }
  .assign-card-accuracy strong { font-size: 28px; }
}
@media (max-width: 520px) {
  .assign-card { grid-template-columns: 82px minmax(0, 1fr); gap: 10px; padding: 10px; }
  .assign-card-thumb { height: 96px; }
  .assign-card-main { grid-template-columns: minmax(0, 1fr) 82px; gap: 8px; }
  .assign-card-question { font-size: 12px; }
  .assign-card-meta { font-size: 11px; }
  .assign-card-accuracy { min-height: 76px; padding: 5px; }
  .accuracy-label { font-size: 10px; }
  .assign-card-accuracy strong { font-size: 24px; }
  .accuracy-steps { font-size: 9px; }
  .queue-row-arrow { display: none; }
}
.student-avatar {
  width: 44px; height: 44px; border-radius: 50%; flex-shrink: 0;
  background: var(--primary-50); color: var(--primary);
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 18px; font-weight: 700;
}
.student-avatar.small { width: 34px; height: 34px; font-size: 15px; }
.student-questions { display: flex; flex-direction: column; gap: 6px; margin-top: 12px; }
.sq-row {
  display: flex; flex-direction: column; gap: 5px; text-align: left; width: 100%;
  background: #fff; border: 1px solid #EDF0F4; border-radius: 10px;
  padding: 9px 11px; cursor: pointer; font-family: inherit;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.sq-row:hover { border-color: #C9D6F2; }
.sq-row.active { border-color: var(--primary); background: var(--primary-50); }
.sq-stem { font-size: 13.5px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sq-badges { display: flex; gap: 6px; flex-wrap: wrap; }
.side-title { font-size: 13px; font-weight: 700; color: var(--text-2); margin-bottom: 10px; }
.queue-row {
  display: flex; align-items: center; gap: 8px; text-align: left;
  background: #fff; border: 1px solid #EDF0F4; border-radius: 10px;
  padding: 11px 12px; cursor: pointer; font-family: inherit; width: 100%;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.queue-row:hover { border-color: #C9D6F2; }
.queue-row.active { border-color: var(--primary); background: var(--primary-50); }
.queue-row-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 5px; }
.queue-row-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 14px; }
.queue-row-meta { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-3); }
.queue-row-arrow { color: var(--text-3); flex-shrink: 0; }
/* 详情弹窗：原图与识别文本在左，诊断过程、错因和审核操作在右。 */
.review-modal-mask {
  position: fixed; inset: 0; z-index: 500;
  display: flex; align-items: center; justify-content: center;
  padding: 24px; background: rgba(20, 31, 28, 0.68);
  backdrop-filter: blur(2px);
}
.review-modal {
  display: flex; flex-direction: column; width: min(1600px, 96vw); height: min(92vh, 1100px);
  overflow: hidden; border: 1px solid #E5EBE6; border-radius: 18px; background: #F7F9F7;
  box-shadow: 0 24px 90px rgba(10, 24, 18, 0.28);
}
.review-modal-header {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  flex: 0 0 66px; padding: 0 24px; border-bottom: 1px solid #E8EDE8; background: #fff;
}
.review-modal-brand { display: flex; align-items: center; gap: 12px; min-width: 0; }
.review-modal-mark {
  width: 42px; height: 42px; flex: 0 0 42px; border-radius: 12px;
  display: inline-flex; align-items: center; justify-content: center;
  color: #fff; background: var(--primary);
}
.review-modal-brand > strong { font-size: 18px; }
.review-modal-title { margin-left: 8px; color: var(--text-3); font-size: 14px; white-space: nowrap; }
.review-modal-meta { margin-left: 8px; color: var(--text-3); font-size: 13px; white-space: nowrap; }
.review-modal-close {
  width: 42px; height: 42px; flex: 0 0 42px; border: 1px solid #E4EAE5; border-radius: 50%;
  background: #fff; color: #718078; font-size: 26px; line-height: 1; cursor: pointer;
}
.review-modal-close:hover { border-color: var(--primary); color: var(--primary); }
.review-modal-body {
  display: grid; grid-template-columns: minmax(220px, 260px) minmax(0, 1fr); gap: 16px;
  min-height: 0; flex: 1; padding: 16px; overflow: hidden;
}
.review-modal-nav { display: flex; flex-direction: column; gap: 9px; min-width: 0; min-height: 0; overflow: auto; }
.review-modal-nav .side-title { padding: 2px 3px; }
.review-modal-nav-group { display: flex; flex-direction: column; gap: 6px; }
.review-modal-nav .queue-row { margin: 0; }
.review-modal-content { display: grid; grid-template-columns: minmax(0, 0.94fr) minmax(0, 1.06fr); gap: 16px; min-width: 0; min-height: 0; overflow: hidden; }
.review-modal-left, .review-modal-right { display: flex; flex-direction: column; gap: 14px; min-width: 0; min-height: 0; overflow: auto; }
.review-modal-panel {
  flex: 0 0 auto; padding: 17px 18px; border: 1px solid #E4EAE5; border-radius: 16px;
  background: #fff; box-shadow: 0 1px 3px rgba(18, 35, 25, 0.035);
}
.review-panel-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 13px; }
.review-panel-heading h3, .review-modal-panel > h3 { margin: 0; font-size: 20px; }
.review-panel-heading > span { max-width: 55%; color: var(--text-3); font-size: 13px; text-align: right; overflow-wrap: anywhere; }
.review-original-image-link {
  display: flex; align-items: center; justify-content: center; min-height: 190px; max-height: 43vh;
  overflow: hidden; border-radius: 10px; background: #F7F8F7;
}
.review-original-image-link img { display: block; width: 100%; height: 100%; max-height: 43vh; object-fit: contain; }
.review-image-empty {
  display: grid; place-items: center; min-height: 190px; padding: 16px; border-radius: 10px;
  background: #F7F8F7; color: var(--text-3); text-align: center;
}
.review-question-text { padding: 15px 16px; border: 1px solid #E6ECE7; border-radius: 12px; background: #FAFBFA; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.85; }
.review-process-note { margin-bottom: 12px; padding: 12px 14px; border-left: 4px solid #D97706; border-radius: 8px; background: #FFFBEB; color: #854D0E; }
.review-process-note p { margin: 4px 0; }
.review-process-note small { display: block; margin-top: 7px; color: var(--text-2); }
.review-solution-steps { display: flex; flex-direction: column; gap: 9px; }
.review-solution-step { padding: 12px 14px; border: 1px solid #E7EAED; border-left: 4px solid #D1D5DB; border-radius: 10px; background: #fff; }
.review-solution-step.is-error { border-left-color: #DC6B63; background: #FFFAF9; }
.review-solution-step.is-correct { border-left-color: #67A77A; }
.review-solution-step-head { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 5px; color: var(--text-3); font-size: 13px; }
.review-solution-step.is-error .review-solution-step-head { color: #B42318; }
.review-solution-step.is-correct .review-solution-step-head { color: #187247; }
.review-solution-step p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; }
.review-empty-note, .review-panel-note { color: var(--text-3); font-size: 13px; }
.review-panel-note { margin: -3px 0 8px; }
.review-modal-loading { display: grid; place-items: center; flex: 1; min-height: 200px; padding: 24px; }
.review-modal .review-error { padding: 14px 0; border-bottom: 1px solid #EDF0ED; }
.review-modal .review-error:last-child { border-bottom: 0; padding-bottom: 0; }
.review-error-head { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; color: var(--text-2); font-size: 13px; }
.conf-text { margin-left: auto; color: var(--text-3); }
.review-error-step { color: var(--text-3); font-size: 13px; }
.review-score-panel > h3 { margin-bottom: 9px; }
.review-modal .approve-bar { position: sticky; bottom: 0; box-shadow: 0 -8px 20px rgba(255, 255, 255, 0.85); }
.review-modal .approve-actions { padding-top: 2px; }
.review-modal .correct-row select, .review-modal .correct-row input { min-height: 38px; }
.review-modal .score-editor { background: #FAFBFA; }
.detail-text { margin-top: 8px; font-size: 14px; color: var(--text-2); }
.review-error { padding: 12px 0; border-bottom: 1px solid #F1F3F6; }
.review-error:last-child { border-bottom: none; padding-bottom: 2px; }
.correct-row { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.correct-row select { width: 150px; flex-shrink: 0; }
.correct-row input { flex: 1; min-width: 140px; width: auto; }
.approve-bar { display: flex; flex-direction: column; gap: 12px; }
.approve-actions { display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.score-line { font-size: 14.5px; }
.score-line b { color: var(--primary); }
/* 最终分编辑器（v0.13.12）：大数字输入 + 分后缀 + 满分参照 + 快捷钮 */
.score-editor { border: 1.5px solid var(--border); border-radius: 12px; padding: 13px 14px; background: var(--bg); }
.score-editor-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.score-editor-row label { font-size: 14px; font-weight: 700; }
.score-editor-row.sub { margin-top: 9px; justify-content: space-between; }
.score-input-wrap {
  display: inline-flex; align-items: center; gap: 2px;
  border: 1.5px solid var(--border); border-radius: 10px; background: #fff;
  padding: 0 12px 0 4px; transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.score-input-wrap:focus-within { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-50); }
.score-input-wrap.changed { border-color: var(--primary); }
.score-input-wrap input {
  width: 92px; border: none; background: transparent; box-shadow: none;
  font-size: 19px; font-weight: 700; color: var(--text); text-align: right;
  padding: 8px 4px; font-variant-numeric: tabular-nums;
}
.score-input-wrap input:focus { outline: none; }
.score-input-wrap.changed input { color: var(--primary); }
.score-suffix { font-size: 14px; color: var(--text-3); font-weight: 600; }
.score-max { font-size: 13.5px; color: var(--text-2); }
.score-quick { display: inline-flex; gap: 6px; }
.chip-btn {
  border: 1px solid var(--border); background: #fff; color: var(--text-2);
  border-radius: 999px; padding: 4px 12px; font-size: 12.5px; font-weight: 600;
  cursor: pointer; font-family: inherit;
}
.chip-btn:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.chip-btn:disabled { opacity: 0.45; cursor: default; }
.ok-line { font-size: 14.5px; color: #065F46; margin-top: 4px; }
.process-card { border-left: 4px solid var(--amber, #D97706); background: #FFFBEB; }
.process-title { display: flex; align-items: center; gap: 7px; }
.process-icon { color: var(--amber, #D97706); flex-shrink: 0; }
.process-signals { margin: 6px 0 8px; padding-left: 20px; font-size: 14px; color: var(--text-2); }
.process-signals li { margin: 3px 0; }
@media (max-width: 900px) {
  .review-modal-mask { padding: 10px; }
  .review-modal { width: 100%; height: 96vh; border-radius: 13px; }
  .review-modal-body { grid-template-columns: 1fr; overflow: auto; }
  .review-modal-nav { max-height: 28vh; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
  .review-modal-content { grid-template-columns: 1fr; overflow: visible; }
  .review-modal-left, .review-modal-right { overflow: visible; }
  .review-original-image-link, .review-original-image-link img { max-height: 38vh; }
}
@media (max-width: 560px) {
  .review-modal-header { flex-basis: 58px; padding: 0 12px; }
  .review-modal-brand { gap: 8px; }
  .review-modal-mark { width: 36px; height: 36px; flex-basis: 36px; }
  .review-modal-brand > strong { font-size: 16px; }
  .review-modal-title { margin-left: 0; font-size: 12px; }
  .review-modal-meta { display: none; }
  .review-modal-body { padding: 10px; gap: 10px; }
  .review-modal-panel { padding: 13px; }
  .review-panel-heading h3, .review-modal-panel > h3 { font-size: 17px; }
  .review-modal .approve-actions { align-items: stretch; }
  .review-modal .approve-actions .btn { width: 100%; }
}
</style>
