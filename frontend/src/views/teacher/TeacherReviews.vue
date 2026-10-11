<!-- 教师端：待审核（v0.9.0 新增）——低置信度错因由老师复核，通过后学生才看得到诊断。
     v0.13.12 重构为三级：先按作业分（一个个作业卡），点进作业后按学生分，
     左边是学生个人信息、右边是该生的答题情况（过程提示/分步诊断/错因复核/
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
      <p class="page-sub">错因判断置信率低于 60% 的作答会进入这里复核；先选作业和学生，确认无误后点「通过」，学生就能查看诊断与错题。错因分错了可以先改再通过。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="okMsg" class="ok-msg">{{ okMsg }}</div>
    <div v-if="loading" class="loading">加载待审核队列中…</div>

    <template v-else>
      <!-- ===== 一级：作业列表 ===== -->
      <template v-if="viewAssignmentId === null">
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
              <span class="assign-card-title">{{ g.title }}</span>
              <span class="assign-card-meta">
                <span class="tnum">{{ g.students.length }}</span> 名学生 ·
                待审核 <span class="tnum">{{ g.total }}</span> 份 ·
                <span v-if="g.errorItems" class="meta-bad">有问题 {{ g.errorItems }} 份</span>
                <span v-if="g.total - g.errorItems" class="meta-good">全对 {{ g.total - g.errorItems }} 份</span>
              </span>
              <span class="assign-card-time">最近提交 {{ fmtTime(g.latest) }}</span>
            </span>
            <AppIcon name="chevron-right" :size="18" class="queue-row-arrow" />
          </button>
        </div>
      </template>

      <!-- ===== 二级：作业内（左学生信息 / 右答题情况） ===== -->
      <template v-else>
        <div class="card queue-head">
          <button class="btn small secondary inline-icon" @click="backToAssignments">
            <AppIcon name="chevron-left" :size="15" /> 返回作业列表
          </button>
          <span class="queue-count">
            {{ currentAssignment?.title }} · 待审核 <b class="tnum">{{ currentAssignment?.total ?? 0 }}</b> 份
          </span>
          <span class="hint">先在左边选学生，右边看他的答题情况</span>
        </div>

        <div class="review-grid">
          <!-- 左列：学生信息 + 学生名单 + 该生题目 -->
          <div class="review-side">
            <div class="card student-info-card" v-if="currentStudent">
              <div class="student-info-head">
                <span class="student-avatar">{{ currentStudent.name.slice(0, 1) }}</span>
                <div class="student-info-main">
                  <router-link :to="`/teacher/students/${currentStudent.id}`" class="student-name">{{ currentStudent.name }}</router-link>
                  <span class="student-no">学号 {{ currentStudent.student_no }}</span>
                </div>
              </div>
              <div class="student-info-stats">
                <span>本作业待审核 <b class="tnum">{{ currentStudentItems.length }}</b> 题</span>
                <span v-if="currentStudentErrorItems">有问题 <b class="tnum bad">{{ currentStudentErrorItems }}</b> 题</span>
                <span v-else>目前全对</span>
              </div>
              <div class="student-questions">
                <button
                  v-for="it in currentStudentItems"
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

            <div class="card queue-card">
              <p class="side-title">本作业的学生（{{ currentAssignment?.students.length ?? 0 }}）</p>
              <button
                v-for="sg in currentAssignment?.students ?? []"
                :key="sg.student.id"
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
                <AppIcon name="chevron-right" :size="16" class="queue-row-arrow" />
              </button>
            </div>
          </div>

          <!-- 右列：答题情况 -->
          <div class="review-detail">
            <div v-if="detailLoading" class="card"><div class="loading">加载诊断中…</div></div>
            <template v-else-if="detail">
              <div class="card">
                <h3>答题情况</h3>
                <p style="font-size: 14px">
                  题目：<strong>{{ detail.question.stem }}</strong>
                  · 提交时间：{{ fmtTime(detail.submitted_at) }}
                </p>
              </div>

              <div class="card process-card" v-if="detail.process_check?.suspicious">
                <h3 class="process-title">
                  <AppIcon name="alert" :size="17" class="process-icon" />
                  过程提示
                </h3>
                <p class="card-sub">供审核参考：该生最终答案正确，但作答过程存在下列情况。</p>
                <ul class="process-signals">
                  <li v-for="s in detail.process_check.signals" :key="s.code">{{ s.text }}</li>
                </ul>
                <p class="hint" v-if="detail.process_check.final_answer || detail.process_check.reference_answer">
                  学生最终答案：{{ detail.process_check.final_answer ?? '—' }}
                  · 参考答案：{{ detail.process_check.reference_answer ?? '—' }}
                </p>
              </div>

              <div class="card">
                <h3>分步诊断</h3>
                <div class="review-steps">
                  <div
                    v-for="st in detail.diagnosis.steps"
                    :key="st.seq"
                    class="review-step"
                    :class="{ 'is-error': st.status === 'error', 'is-correct': st.status === 'ok' }"
                  >
                    <div class="review-step-title">{{ st.seq === 0 ? '题干' : `步骤 ${st.seq}` }} · {{ STEP_STATUS_TEXT[st.status] }}</div>
                    <p>{{ st.text }}</p>
                  </div>
                </div>
                <p v-if="!detail.diagnosis.errors.length" class="ok-line">这份作答全部正确，通过后学生会看到鼓励反馈。</p>
              </div>

              <div class="card" v-if="detail.diagnosis.errors.length">
                <h3>错因复核</h3>
                <p class="card-sub">分类不对的先在这里改，改完点下方「通过」就是改后通过（纠错会照常回标入库；待审核期间不会提前通知学生）。</p>
                <div v-for="e in detail.diagnosis.errors" :key="e.id" class="review-error">
                  <p>
                    <ErrorTypeBadge :type="e.error_type" />
                    <span class="badge badge-blue">{{ e.knowledge_point }}</span>
                    <span class="conf-text tnum">置信度 {{ Math.round(e.confidence * 100) }}%</span>
                    <span v-if="e.is_stubborn" class="badge badge-red">顽固误区</span>
                    <span v-if="e.teacher_corrected" class="badge badge-gray">已纠错</span>
                  </p>
                  <p class="detail-text">{{ e.detail }}</p>
                  <p v-if="e.step_text" class="detail-text">出错步骤：{{ e.step_text }}</p>
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
              </div>

              <div class="card" v-if="detail.score">
                <h3>AI 评分</h3>
                <p class="score-line">
                  本题满分 <b class="tnum">{{ fmtScore(detail.score.question_max) }}</b> 分 ·
                  AI 评分 <b class="tnum">{{ detail.score.ai_score !== null ? fmtScore(detail.score.ai_score) : '—' }}</b> 分
                  <span class="hint">（按步骤对错折算：步骤对了 {{ detail.score.ok_steps }}/{{ detail.score.total_steps }} 步）</span>
                </p>
                <p v-if="detail.score.final_score !== null" class="score-line" style="margin-top: 6px">
                  最终分 <b class="tnum">{{ fmtScore(detail.score.final_score) }}</b> 分（已落定）
                </p>
                <p v-else class="hint" style="margin-top: 6px">觉得 AI 分不准，可以在下方通过时改分；不改就按 AI 评分给学生。</p>
              </div>

              <div class="card approve-bar">
                <!-- v0.13.12：最终分改成正式的分值编辑器——大号数字输入（带「分」
                     后缀）、满分参照、快捷钮（用 AI 评分 / 满分）；文本输入避免
                     type=number 的 v-model 自动转数字坑 -->
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
                    <span class="hint">留空 = 用 AI 评分；填了就按这个分落定，学生看到的是最终分。</span>
                    <span class="score-quick">
                      <button type="button" class="chip-btn" :disabled="!scoreChanged" @click="finalScoreInput = ''">用 AI 评分</button>
                      <button type="button" class="chip-btn" @click="finalScoreInput = fmtScore(detail.score.question_max)">给满分</button>
                    </span>
                  </div>
                </div>
                <div class="approve-actions">
                  <p class="hint" style="margin: 0">通过后，学生会立刻收到一条提醒，并能看到这份诊断与错题。</p>
                  <button class="btn" :disabled="approving" @click="approveSelected">
                    {{ approving ? '通过中…' : '通过审核' }}
                  </button>
                </div>
              </div>
            </template>
            <div v-else class="card">
              <div class="empty">从左边选一位学生，右边会显示他的答题情况。</div>
            </div>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useTeacherStore } from '../../stores/teacher'
import type { ReviewDetail, ReviewPendingItem } from '../../api/types'
import { ERROR_TYPES, STEP_STATUS_TEXT } from '../../api/types'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import AppIcon from '../../components/icons/AppIcon.vue'

const teacher = useTeacherStore()
const route = useRoute()

const items = ref<ReviewPendingItem[]>([])
const selectedId = ref<number | null>(null)
const detail = ref<ReviewDetail | null>(null)
const loading = ref(false)
const detailLoading = ref(false)
const approving = ref(false)
const approvingAll = ref(false)
const correctingId = ref<number | null>(null)
const error = ref('')
const okMsg = ref('')
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

// ---------- v0.13.12：按作业、按学生分组 ----------

type StudentOfItem = ReviewPendingItem['student']
interface StudentGroup { student: StudentOfItem; items: ReviewPendingItem[] }
interface AssignmentGroup {
  id: number | null
  title: string
  students: StudentGroup[]
  total: number
  errorItems: number
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
    if (it.submitted_at > g.latest) g.latest = it.submitted_at
    if (it.image_url) g.imageUrl = it.image_url
  }
  return [...map.values()]
})

/** 当前所在层级：null = 作业列表；否则是作业 id（字符串键，与分组口径一致） */
const viewAssignmentId = ref<string | null>(null)
const selectedStudentId = ref<number | null>(null)

const currentAssignment = computed(() =>
  assignmentGroups.value.find((g) => String(g.id) === viewAssignmentId.value) ?? null
)
const currentStudentGroup = computed(() =>
  currentAssignment.value?.students.find((s) => s.student.id === selectedStudentId.value) ?? null
)
const currentStudent = computed(() => currentStudentGroup.value?.student ?? null)
const currentStudentItems = computed(() => currentStudentGroup.value?.items ?? [])
const currentStudentErrorItems = computed(() =>
  currentStudentItems.value.filter((i) => i.error_count).length
)

function enterAssignment(g: AssignmentGroup) {
  viewAssignmentId.value = String(g.id)
  const first = g.students[0]
  if (first) {
    selectedStudentId.value = first.student.id
    void selectItem(first.items[0].submission_id)
  }
}

function backToAssignments() {
  viewAssignmentId.value = null
  selectedStudentId.value = null
  selectedId.value = null
  detail.value = null
}

function selectStudent(studentId: number) {
  selectedStudentId.value = studentId
  const sg = currentAssignment.value?.students.find((s) => s.student.id === studentId)
  if (sg?.items.length) void selectItem(sg.items[0].submission_id)
}

/** 通过一份后重新定位：同学生下一题 → 同作业下一位学生 → 回作业列表 */
async function relocateAfterApprove(assignmentKey: string | null, studentId: number | null) {
  const g = assignmentGroups.value.find((x) => String(x.id) === assignmentKey)
  if (viewAssignmentId.value !== null && g) {
    const sg = g.students.find((s) => s.student.id === studentId) ?? g.students[0]
    if (sg) {
      selectedStudentId.value = sg.student.id
      await selectItem(sg.items[0].submission_id)
      return
    }
  }
  backToAssignments()
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

async function selectItem(submissionId: number) {
  selectedId.value = submissionId
  detailLoading.value = true
  detail.value = null
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
  const preset = Number(route.query.submission_id)
  void loadQueue(preset || undefined)
})
</script>

<style scoped>
.queue-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 18px; flex-wrap: wrap; }
.queue-count { font-size: 15px; font-weight: 600; }
.queue-count b { color: var(--primary); font-size: 19px; }
/* 一级：作业卡列表 */
.assign-list { display: flex; flex-direction: column; gap: 10px; }
.assign-card {
  display: flex; align-items: center; gap: 12px; text-align: left; width: 100%;
  padding: 16px 18px; cursor: pointer; font-family: inherit; margin-bottom: 0;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.assign-card:hover { border-color: #C9D6F2; }
.assign-card-thumb {
  width: 32%; max-width: 400px; min-width: 200px; height: 116px; flex: 0 0 32%;
  display: flex; align-items: center; justify-content: center; overflow: hidden;
  border: 1px solid var(--border); border-radius: 10px; background: #F8FAFC;
}
.assign-card-thumb img { width: 100%; height: 100%; object-fit: contain; }
.assign-card-thumb-empty { color: var(--text-3); font-size: 13px; }
.assign-card-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 5px; }
.assign-card-title { font-size: 16px; font-weight: 700; }
.assign-card-meta { font-size: 13px; color: var(--text-2); }
.assign-card-time { font-size: 12px; color: var(--text-3); }
.meta-bad { color: #B91C1C; font-weight: 600; }
.meta-good { color: #15803D; font-weight: 600; }
/* 二级：左列（学生信息 + 名单）/ 右列（答题情况） */
.review-grid { display: grid; grid-template-columns: 320px 1fr; gap: 16px; align-items: start; }
@media (max-width: 1080px) {
  .review-grid { grid-template-columns: 1fr; }
}
@media (max-width: 760px) {
  .assign-card { flex-wrap: wrap; }
  .assign-card-thumb { width: 100%; max-width: none; min-width: 0; flex-basis: 100%; height: 180px; }
}
.review-side { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.student-info-card { padding: 16px 18px; }
.student-info-head { display: flex; align-items: center; gap: 12px; }
.student-avatar {
  width: 44px; height: 44px; border-radius: 50%; flex-shrink: 0;
  background: var(--primary-50); color: var(--primary);
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 18px; font-weight: 700;
}
.student-avatar.small { width: 34px; height: 34px; font-size: 15px; }
.student-info-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.student-name { font-size: 16px; font-weight: 700; color: var(--primary); text-decoration: none; }
.student-no { font-size: 12.5px; color: var(--text-3); }
.student-info-stats { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 12px; font-size: 13px; color: var(--text-2); }
.student-info-stats b { color: var(--primary); }
.student-info-stats b.bad { color: #B91C1C; }
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
.queue-card { padding: 10px; display: flex; flex-direction: column; gap: 6px; }
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
.review-detail > .card:last-child { margin-bottom: 0; }
.review-steps { display: flex; flex-direction: column; }
.review-step { padding: 10px 0; border-bottom: 1px solid #F1F3F6; }
.review-step:first-child { padding-top: 2px; }
.review-step:last-child { border-bottom: 0; padding-bottom: 2px; }
.review-step-title { margin-bottom: 4px; font-size: 13px; font-weight: 600; color: var(--text-3); }
.review-step.is-error .review-step-title { color: #991B1B; }
.review-step.is-correct .review-step-title { color: #065F46; }
.review-step p { margin: 0; font-size: 15px; }
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
</style>
