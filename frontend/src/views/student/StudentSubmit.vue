<!-- 学生端：交作业（v0.2.1 拍照为主；v0.3.0 拍照批改原地完成；v0.6.0 一键直达）
     v0.9.0：作业切换改成页面顶部一条独立 sticky 切换条（下拉选作业，原地切换，
     与下方题目列表视觉分开，不再混在题目卡里）；新批改先过老师审核——
     提交后题目状态显示「待老师审核」，审核通过后诊断才可见。
     v0.9.2 两项逻辑纠正：
     ① 作答方式按作业模式分流——线上作业（mode=online）恢复「在线作答」：
        每道题卡内是文本编辑器（一行一步），提交走 3.3 文本提交接口，与拍照
        完全同链（先 AI 诊断产出步骤诊断与错因，再建 pending 审核行）；
        线下练习册（mode=offline）保持拍照批改。草稿按题目存 localStorage。
     ② 拍照批改点按直达图库：行内按钮点击当下就调 PhotoGradeFlow.openPicker()
        打开系统图库/文件选择，不再先展开一层中间面板；取消选择不留空面板。
     入口：从作业列表进入 /student/submit?assignment_id=；直接访问时用切换条选择。
     契约：3.1 作业列表 / 3.2 作业详情 / 3.3 文本提交（在线作答）/ 3.4 我的提交记录 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>交作业</h2>
      <p class="page-sub">{{ headSub }}</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-else>
      <!-- 作业切换条（v0.9.0）：钉在页面顶部，与题目列表分开 -->
      <div class="card switch-bar">
        <label class="switch-label" for="submit-assignment-select">
          <AppIcon name="clipboard" :size="16" /> 正在交的作业
        </label>
        <select id="submit-assignment-select" v-model="assignmentId" class="switch-select" @change="onAssignmentChange">
          <option value="">请选择一份作业…</option>
          <option v-for="a in assignments" :key="a.id" :value="a.id">
            {{ a.title }}（{{ a.question_count }} 题）{{ a.mode === 'offline' ? ' · 线下练习' : ' · 线上作业' }}
          </option>
        </select>
        <router-link to="/student/assignments" class="switch-all">全部作业 <AppIcon name="chevron-right" :size="13" /></router-link>
      </div>

      <!-- 当前作业说明（与切换条分开的独立信息卡） -->
      <div v-if="currentDetail" class="card assign-info">
        <p>
          <strong>{{ currentDetail.title }}</strong>
          <span v-if="currentDetail.mode === 'offline'" class="badge badge-amber" style="margin-left: 8px">线下练习</span>
          <span v-else class="badge badge-blue" style="margin-left: 8px">线上作业</span>
        </p>
        <p class="kp">{{ currentDetail.description || '暂无说明' }}</p>
        <p v-if="currentDetail.mode === 'offline'" class="kp" style="margin-top: 4px">
          <template v-if="currentDetail.workbook_title">{{ currentDetail.workbook_title }}</template>
          <template v-if="currentDetail.page_range"> · {{ currentDetail.page_range }}</template>
          <template v-if="currentDetail.deadline"> · 截止 {{ currentDetail.deadline.replace('T', ' ').slice(0, 16) }}</template>
          —— 在练习册上做完后，逐题拍照提交就可以啦。
        </p>
        <p v-else class="kp" style="margin-top: 4px">
          线上作业：在每道题下方点「在线作答」，把解题步骤一行一步写下来提交就可以啦。
        </p>
      </div>

      <div v-if="mathQuestions.length" class="card">
        <h3>题目列表</h3>
        <p class="card-sub">{{ listSub }}</p>
        <div v-for="q in mathQuestions" :key="q.id" class="q-block">
          <div class="q-row">
            <span class="q-order tnum">{{ q.order_num }}</span>
            <div class="q-main">
              <p class="q-stem">{{ q.stem }}</p>
              <p class="q-meta">
                <span class="badge badge-blue">{{ q.knowledge_point }}</span>
                <span v-if="pendingQids.has(q.id)" class="badge badge-amber">待老师审核</span>
                <span v-else-if="doneQids.has(q.id)" class="badge badge-green">已完成</span>
                <span v-else class="badge badge-gray">未完成</span>
                <span v-if="scoreByQid[q.id]" class="badge badge-green tnum">得分 {{ fmtScore(scoreByQid[q.id].score) }} / {{ fmtScore(scoreByQid[q.id].max) }} 分</span>
              </p>
            </div>
            <!-- 线下：点按直达图库（v0.9.2），不再先展开中间面板 -->
            <template v-if="isOffline">
              <button class="btn inline-icon" @click="pickPhoto(q.id)">
                <AppIcon name="camera" :size="16" />
                {{ flowActive[q.id] ? '重新拍照' : '拍照批改' }}
              </button>
              <button v-if="flowActive[q.id]" class="btn secondary small" @click="toggleCollapse(q.id)">
                {{ collapsedQids.has(q.id) ? '展开结果' : '收起' }}
              </button>
            </template>
            <!-- 线上：展开本题内的在线作答编辑器 -->
            <button v-else class="btn inline-icon" @click="toggleEditor(q.id)">
              <AppIcon name="edit" :size="16" />
              {{ editorOpen[q.id] ? '收起' : doneQids.has(q.id) || pendingQids.has(q.id) ? '再交一次' : '在线作答' }}
            </button>
          </div>

          <!-- 线下拍照流：组件常驻挂载（idle 时不可见），按钮点按经 ref 直达图库 -->
          <div v-if="isOffline" v-show="!collapsedQids.has(q.id)" class="flow-slot" :class="{ 'has-content': flowActive[q.id] }">
            <PhotoGradeFlow
              :ref="(el) => setFlowRef(q.id, el)"
              :question-id="q.id"
              :question-stem="q.stem"
              direct
              @graded="onGraded(q.id, $event)"
              @active="onFlowActive(q.id, $event)"
            />
          </div>

          <!-- 线上在线作答（v0.9.2）：一行一步，草稿自动保存在本机 -->
          <div v-if="!isOffline && editorOpen[q.id]" class="answer-editor">
            <div class="editor-wrap">
              <div class="editor-gutter" aria-hidden="true">
                <div class="editor-gutter-inner" :style="{ transform: `translateY(${-(gutterScroll[q.id] ?? 0)}px)` }">
                  <span v-for="n in lineCount(q.id)" :key="n" class="tnum">{{ n }}</span>
                </div>
              </div>
              <textarea
                :value="drafts[q.id] ?? ''"
                class="answer-textarea"
                spellcheck="false"
                placeholder="每行写一步解题过程，最后一行写最终答案。例如：&#10;2x + 3 = 7&#10;2x = 4&#10;x = 2"
                @input="onDraftInput(q.id, $event)"
                @scroll="onEditorScroll(q.id, $event)"
              />
            </div>
            <div class="editor-meta">
              <span class="tnum">{{ stepCount(q.id) }} / 20 步</span>
              <span v-if="stepCount(q.id) > 20" class="editor-warn">步骤有点多，最多 20 步，请把几步合并一下再提交。</span>
              <span v-else-if="(drafts[q.id] ?? '').trim()" class="editor-saved">草稿已自动保存在这台设备上</span>
            </div>
            <div class="toolbar" style="margin: 10px 0 0">
              <button
                class="btn"
                :disabled="submittingMap[q.id] || stepCount(q.id) === 0 || stepCount(q.id) > 20"
                @click="submitAnswer(q)"
              >
                {{ submittingMap[q.id] ? '提交中…' : '提交作答' }}
              </button>
              <button class="btn secondary" :disabled="submittingMap[q.id]" @click="clearDraft(q.id)">清空重写</button>
            </div>
            <div v-if="answerErrors[q.id]" class="error-msg" style="margin-top: 10px">{{ answerErrors[q.id] }}</div>
          </div>

          <!-- 线上提交后的状态卡（与拍照流同一套待审核语义） -->
          <div v-if="!isOffline && submittedNotes[q.id] === 'pending'" class="review-pending-box">
            <span class="review-pending-icon"><AppIcon name="history" :size="17" /></span>
            <div>
              <p class="review-pending-title">已提交，老师审核后你会收到诊断</p>
              <p class="review-pending-sub">老师确认批改无误后，诊断和错题会自动出现在报告与错题本里。想改的话，点上方「再交一次」重新作答即可。</p>
            </div>
          </div>
          <p v-else-if="!isOffline && submittedNotes[q.id] === 'approved'" class="submit-ok-line">
            <AppIcon name="check" :size="15" /> 已提交，批改结果已生成，去学习报告或错题本看看吧。
          </p>
        </div>
      </div>

      <div v-else-if="assignmentId" class="card">
        <div class="empty">这份作业暂时没有可作答的题目。</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStudentStore } from '../../stores/student'
import type { Assignment, AssignmentDetail, Question, SubmissionResult } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'
import PhotoGradeFlow from '../../components/PhotoGradeFlow.vue'

const student = useStudentStore()
const route = useRoute()
const router = useRouter()

const assignments = ref<Assignment[]>([])
const assignmentId = ref<number | ''>('')
const currentDetail = ref<AssignmentDetail | null>(null) // 当前所选作业详情（说明卡 + 题目来源）
const questions = ref<Question[]>([])
const doneQids = ref<Set<number>>(new Set())
const pendingQids = ref<Set<number>>(new Set()) // v0.9.0：最新一次提交在等老师审核的题目
const scoreByQid = ref<Record<number, { score: number; max: number }>>({}) // 评分系统：已通过题目的得分 chip
const loading = ref(false)
const error = ref('')

const mathQuestions = computed(() => questions.value.filter((q) => q.subject === 'math'))
/** 作答方式按作业模式分流：offline=线下练习册走拍照，其余（online）走在线作答 */
const isOffline = computed(() => currentDetail.value?.mode === 'offline')

const headSub = computed(() => {
  if (!currentDetail.value) return '先在上方选一份作业，再逐题完成作答；老师审核后就能看到逐步批改。'
  return isOffline.value
    ? '选好题目，拍一张作答照片；老师审核后就能看到逐步批改。'
    : '在线写下每道题的解题步骤提交；老师审核后就能看到逐步批改。'
})
const listSub = computed(() =>
  isOffline.value
    ? '点任意一题的「拍照批改」会直接打开图库，选好照片就在本题这里出结果，不用跳页面。'
    : '点任意一题的「在线作答」，在本题这里把解题步骤一行一步写下来提交，不用跳页面。'
)

/* ---------- 线下拍照流：点按直达图库（v0.9.2） ---------- */
type FlowHandle = { openPicker: () => void }
const flowRefs = new Map<number, FlowHandle | null>()
const flowActive = ref<Record<number, boolean>>({})
const collapsedQids = ref<Set<number>>(new Set())

function setFlowRef(qid: number, el: unknown) {
  flowRefs.set(qid, (el as FlowHandle | null) ?? null)
}

/** 点「拍照批改」的当下就打开图库，不再先展开一层中间面板 */
function pickPhoto(qid: number) {
  collapsedQids.value = new Set([...collapsedQids.value].filter((x) => x !== qid))
  flowRefs.get(qid)?.openPicker()
}

function onFlowActive(qid: number, active: boolean) {
  flowActive.value = { ...flowActive.value, [qid]: active }
}

function toggleCollapse(qid: number) {
  const next = new Set(collapsedQids.value)
  if (next.has(qid)) next.delete(qid)
  else next.add(qid)
  collapsedQids.value = next
}

/* ---------- 线上在线作答（v0.9.2） ---------- */
const MAX_STEPS = 20 // 与后端 SubmissionCreate.steps 上限一致
const drafts = ref<Record<number, string>>({})
const editorOpen = ref<Record<number, boolean>>({})
const submittingMap = ref<Record<number, boolean>>({})
const answerErrors = ref<Record<number, string>>({})
const submittedNotes = ref<Record<number, 'pending' | 'approved'>>({})
const gutterScroll = ref<Record<number, number>>({})

const draftKey = (qid: number) => `remedi-answer-draft-${qid}`

function lineCount(qid: number): number {
  return Math.max(1, (drafts.value[qid] ?? '').split('\n').length)
}

function stepCount(qid: number): number {
  return (drafts.value[qid] ?? '').split('\n').map((s) => s.trim()).filter(Boolean).length
}

function onDraftInput(qid: number, e: Event) {
  const text = (e.target as HTMLTextAreaElement).value
  drafts.value = { ...drafts.value, [qid]: text }
  // 草稿按题目存本机，交完清除（见 submitAnswer）
  if (text) localStorage.setItem(draftKey(qid), text)
  else localStorage.removeItem(draftKey(qid))
}

function onEditorScroll(qid: number, e: Event) {
  gutterScroll.value = { ...gutterScroll.value, [qid]: (e.target as HTMLTextAreaElement).scrollTop }
}

function clearDraft(qid: number) {
  drafts.value = { ...drafts.value, [qid]: '' }
  localStorage.removeItem(draftKey(qid))
  answerErrors.value = { ...answerErrors.value, [qid]: '' }
}

function toggleEditor(qid: number) {
  const opening = !editorOpen.value[qid]
  editorOpen.value = { ...editorOpen.value, [qid]: opening }
  if (opening) {
    // 重新作答时收起上次提交的状态卡，避免与编辑器同时出现
    const notes = { ...submittedNotes.value }
    delete notes[qid]
    submittedNotes.value = notes
  }
}

function errDetail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof d === 'string' ? d : ''
}

function fmtScore(v: number): string {
  return String(Math.round(v * 10) / 10)
}

/** 在线提交：与拍照完全同链——后端先 AI 诊断，再进教师待审核（3.3） */
async function submitAnswer(q: Question) {
  const steps = (drafts.value[q.id] ?? '').split('\n').map((s) => s.trim()).filter(Boolean)
  if (!steps.length) {
    answerErrors.value = { ...answerErrors.value, [q.id]: '先写下你的解题步骤再提交。' }
    return
  }
  if (steps.length > MAX_STEPS) {
    answerErrors.value = { ...answerErrors.value, [q.id]: `步骤最多 ${MAX_STEPS} 步，请把几步合并一下再提交。` }
    return
  }
  answerErrors.value = { ...answerErrors.value, [q.id]: '' }
  submittingMap.value = { ...submittingMap.value, [q.id]: true }
  try {
    const res = await student.submitMath({ question_id: q.id, steps })
    clearDraft(q.id)
    editorOpen.value = { ...editorOpen.value, [q.id]: false }
    submittedNotes.value = {
      ...submittedNotes.value,
      [q.id]: res.status === 'pending_review' || res.review_status === 'pending' ? 'pending' : 'approved'
    }
    onGraded(q.id, res)
  } catch (e) {
    answerErrors.value = { ...answerErrors.value, [q.id]: '提交失败：' + (errDetail(e) || '请稍后重试。') }
    console.error(e)
  } finally {
    submittingMap.value = { ...submittingMap.value, [q.id]: false }
  }
}

/* ---------- 作业装载与状态 ---------- */

async function loadQuestions(id: number) {
  const detail = await student.fetchAssignmentDetail(id)
  questions.value = detail.questions
  currentDetail.value = detail
  // 恢复本机草稿（按题目），并为线上作业自动展开第一道未完成题的编辑器
  const restored: Record<number, string> = {}
  detail.questions.forEach((q) => {
    const saved = localStorage.getItem(draftKey(q.id))
    if (saved) restored[q.id] = saved
  })
  drafts.value = { ...drafts.value, ...restored }
  if (detail.mode !== 'offline') {
    const firstOpen = detail.questions.find(
      (q) => q.subject === 'math' && !doneQids.value.has(q.id) && !pendingQids.value.has(q.id)
    )
    if (firstOpen) editorOpen.value = { ...editorOpen.value, [firstOpen.id]: true }
  }
  return detail
}

async function selectAssignment(id: number) {
  questions.value = []
  currentDetail.value = null
  flowActive.value = {}
  collapsedQids.value = new Set()
  editorOpen.value = {}
  submittedNotes.value = {}
  answerErrors.value = {}
  if (!id) return
  try {
    await loadQuestions(id)
  } catch (e) {
    error.value = '作业详情加载失败。'
    console.error(e)
  }
}

async function onAssignmentChange() {
  const id = Number(assignmentId.value)
  // 地址栏同步当前作业，刷新/分享链接都落回这份作业
  router.replace({ query: id ? { assignment_id: id } : {} })
  await selectAssignment(id)
}

/** 批改完成（v0.9.0）：新提交先过老师审核——pending 进待审核集，否则进已完成集 */
function onGraded(qid: number, result: SubmissionResult) {
  if (result.status === 'pending_review' || result.review_status === 'pending') {
    pendingQids.value = new Set(pendingQids.value).add(qid)
    doneQids.value = new Set([...doneQids.value].filter((x) => x !== qid))
    // 重新提交后旧分数作废（新分要等老师审核通过才有）
    const scores = { ...scoreByQid.value }
    delete scores[qid]
    scoreByQid.value = scores
  } else {
    doneQids.value = new Set(doneQids.value).add(qid)
    pendingQids.value = new Set([...pendingQids.value].filter((x) => x !== qid))
    if (result.score) {
      scoreByQid.value = {
        ...scoreByQid.value,
        [qid]: { score: result.score.score, max: result.score.max_score }
      }
    }
  }
}

onMounted(async () => {
  loading.value = true
  try {
    const [list, subs] = await Promise.all([
      student.fetchAssignments(),
      student.fetchMySubmissions().catch(() => [])
    ])
    assignments.value = list
    // 每道题取最新一次提交定状态（列表按时间倒序，首见即最新）
    const latestByQid = new Map<number, string>()
    subs.forEach((s) => {
      if (!latestByQid.has(s.question_id)) {
        latestByQid.set(s.question_id, s.review_status ?? 'approved')
      }
    })
    latestByQid.forEach((rstatus, qid) => {
      if (rstatus === 'pending') pendingQids.value.add(qid)
      else doneQids.value.add(qid)
    })
    // 评分系统：每题最新一次提交若已通过且有分，记下得分 chip 数据
    const seenScore = new Set<number>()
    const scores: Record<number, { score: number; max: number }> = {}
    subs.forEach((s) => {
      if (seenScore.has(s.question_id)) return
      seenScore.add(s.question_id)
      if (s.score !== null && s.score !== undefined && s.max_score !== null && s.max_score !== undefined) {
        scores[s.question_id] = { score: s.score, max: s.max_score }
      }
    })
    scoreByQid.value = scores
    const presetId = Number(route.query.assignment_id)
    if (presetId && list.some((a) => a.id === presetId)) {
      assignmentId.value = presetId
      try {
        await loadQuestions(presetId)
      } catch {
        error.value = '该作业不存在或已失效，请重新选择。'
      }
    } else if (presetId) {
      error.value = '该作业不存在或已失效，请重新选择。'
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
/* 作业切换条（v0.9.0）：sticky 钉顶，与下方卡片拉开间距和层级 */
.switch-bar {
  position: sticky;
  top: 12px;
  z-index: 60;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px 18px;
  box-shadow: var(--shadow-md);
}
.switch-label {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  white-space: nowrap;
}
.switch-select { flex: 1; min-width: 200px; width: auto; }
.switch-all {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--primary);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}
@media (max-width: 960px) {
  /* 移动端顶栏高 52px，切换条贴在它下方 */
  .switch-bar { top: 60px; }
}
.assign-info { background: var(--primary-50); border-color: #DBEAFE; box-shadow: none; }
.assign-info .kp { color: var(--text-2); font-size: 13px; margin-top: 4px; }
.q-block { border-bottom: 1px solid #F1F3F6; padding-bottom: 12px; }
.q-block:last-child { border-bottom: none; padding-bottom: 0; }
.q-row {
  display: flex; align-items: center; gap: 14px;
  padding: 12px 4px 0;
}
.q-order {
  width: 28px; height: 28px; border-radius: 50%; flex-shrink: 0;
  background: var(--primary-50); color: var(--primary);
  font-weight: 700; font-size: 13.5px;
  display: flex; align-items: center; justify-content: center;
}
.q-main { flex: 1; min-width: 0; }
.q-stem { font-size: 14.5px; font-weight: 500; }
.q-meta { margin-top: 4px; }
/* 拍照流槽位：idle 时不占位，有内容才让组件自带的上边距生效 */
.flow-slot :deep(.pgf) { margin-top: 0; }
.flow-slot.has-content :deep(.pgf) { margin-top: 12px; }
/* 在线作答编辑器（v0.9.2）：左侧行号槽 + 文本域，行高严格对齐 */
.answer-editor { margin: 12px 4px 2px; }
.editor-wrap {
  display: flex;
  height: 208px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
}
.editor-wrap:focus-within { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-50); }
.editor-gutter {
  flex-shrink: 0;
  width: 40px;
  padding: 10px 0;
  background: var(--bg);
  border-right: 1px solid #EDF0F4;
  overflow: hidden;
  text-align: right;
}
.editor-gutter-inner { display: flex; flex-direction: column; will-change: transform; }
.editor-gutter-inner span {
  height: 26px; line-height: 26px;
  padding-right: 10px;
  font-size: 12.5px; color: var(--text-3);
  user-select: none;
}
.answer-textarea {
  flex: 1; min-width: 0;
  height: 100%;
  border: none; border-radius: 0;
  padding: 10px 12px;
  font-size: 14.5px; line-height: 26px;
  resize: none;
  background: transparent;
}
.answer-textarea:focus { outline: none; border: none; box-shadow: none; }
.editor-meta {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  margin-top: 7px; font-size: 12.5px; color: var(--text-3);
}
.editor-warn { color: var(--amber); font-weight: 600; }
.editor-saved { color: var(--text-3); }
/* 待老师审核状态盒（与 PhotoGradeFlow 内同一套语义，保持双端观感一致） */
.review-pending-box {
  display: flex; gap: 11px; align-items: flex-start;
  background: var(--amber-bg); border: 1px solid #FDE68A; border-radius: 10px;
  padding: 13px 15px; margin: 12px 4px 2px;
}
.review-pending-icon { width: 30px; height: 30px; border-radius: 50%; flex-shrink: 0; background: #fff; color: var(--amber); display: flex; align-items: center; justify-content: center; }
.review-pending-title { font-size: 14.5px; font-weight: 700; color: #92400E; }
.review-pending-sub { font-size: 13px; color: #92400E; opacity: 0.85; margin-top: 2px; }
.submit-ok-line {
  display: flex; align-items: center; gap: 6px;
  margin: 12px 4px 2px; font-size: 14px; color: #065F46;
}
</style>
