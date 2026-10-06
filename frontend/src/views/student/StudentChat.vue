<!-- 学生端：智能批改（对话页，v0.2.0 新增，学生登录默认落地页）
     打开先播报首页简报（GET /api/student/briefing）；对话流支持：
       1) 拍照批改：上传照片 → POST /api/student/photo-transcribe 转写卡片（可编辑）
          → 确认后走 POST /api/student/submissions 出诊断卡片
       2) 文本批改：顶部选好题目，步骤按行输入发送即批改
     文案伦理沿用学生端口径：不出现「顽固」「置信度」等术语（与既有页面一致）。 -->
<template>
  <div class="chat-layout">
    <!-- 顶部：题目选择器 -->
    <div class="chat-header">
      <div class="chat-inner">
        <div class="chat-title">
          <AppIcon name="sparkles" :size="20" />
          <span>智能批改</span>
          <span class="hint">拍照或输入步骤，AI 立刻逐步帮你检查</span>
        </div>
        <div class="chat-selectors">
          <select v-model="assignmentId" @change="onAssignmentChange" aria-label="选择作业">
            <option value="">选择作业…</option>
            <option v-for="a in assignments" :key="a.id" :value="a.id">{{ a.title }}</option>
          </select>
          <select v-model="questionId" :disabled="!currentQuestions.length" aria-label="选择题目">
            <option value="">选择题目…</option>
            <option v-for="q in currentQuestions" :key="q.id" :value="q.id">
              [{{ q.subject === 'math' ? '数学' : '作文' }} · {{ q.knowledge_point }}] {{ q.stem }}
            </option>
          </select>
        </div>
        <p v-if="selectedQuestion?.subject === 'english'" class="hint">
          这是作文题，步骤批改只支持数学题；作文请到「交作业」页粘贴全文提交。
        </p>
      </div>
    </div>

    <!-- 消息流 -->
    <div class="chat-body" ref="bodyRef">
      <div class="chat-inner">
        <div v-for="msg in messages" :key="msg.id" class="msg-row" :class="msg.side">
          <div v-if="msg.side === 'ai'" class="msg-avatar"><AppIcon name="sparkles" :size="16" /></div>

          <!-- AI 简报卡 -->
          <div v-if="msg.kind === 'briefing' && msg.briefing" class="ai-card">
            <p class="ai-card-title"><AppIcon name="clipboard" :size="17" /> 学习简报</p>
            <template v-if="briefingAllDone(msg.briefing)">
              <p>太棒了，{{ auth.name }}！作业都完成了，订正也全部搞定，暂时没有需要加固的知识点。</p>
              <p class="review-tip">
                复习建议：把最近做过的题目遮住答案再独立做一遍；也可以去「我的档案」看看自己的错误轨迹，挑一道印象最深的题重做巩固。
              </p>
            </template>
            <template v-else>
              <p>{{ auth.name }}，你好！先看看你现在的进度：</p>

              <div v-if="msg.briefing.pending_assignments.length" class="brief-section">
                <p class="brief-label">还没完成的作业</p>
                <div v-for="p in msg.briefing.pending_assignments" :key="p.id" class="brief-item">
                  <span class="brief-item-main">
                    {{ p.title }}
                    <span class="badge badge-blue tnum">还剩 {{ p.remaining_count }} 题</span>
                  </span>
                  <button class="btn small" @click="gotoAssignment(p)">去完成</button>
                </div>
              </div>

              <div v-if="msg.briefing.pending_corrections_count" class="brief-section">
                <p class="brief-label">待订正提醒</p>
                <p class="brief-line">
                  你有 <strong class="tnum">{{ msg.briefing.pending_corrections_count }}</strong> 处订正还没完成
                  <template v-if="msg.briefing.pending_corrections_knowledge_points.length">
                    ，涉及知识点：{{ msg.briefing.pending_corrections_knowledge_points.join('、') }}
                  </template>
                  。
                  <router-link to="/student/corrections"><button class="btn small secondary">去订正</button></router-link>
                </p>
              </div>

              <div v-if="msg.briefing.weak_points.length" class="brief-section">
                <p class="brief-label">需要加固的知识点</p>
                <p>
                  <span v-for="kp in msg.briefing.weak_points" :key="kp" class="badge badge-amber">{{ kp }}</span>
                </p>
              </div>

              <div v-if="msg.briefing.recent_feedback" class="brief-section">
                <p class="brief-label">最近动态</p>
                <p class="brief-line">{{ sanitizeStudentCopy(msg.briefing.recent_feedback) }}</p>
              </div>
            </template>
          </div>

          <!-- AI 普通文本 -->
          <div v-else-if="msg.kind === 'text' && msg.side === 'ai'" class="bubble ai-bubble">
            <AppIcon v-if="msg.pending" name="spinner" :size="16" class="spin" />
            {{ msg.text }}
          </div>

          <!-- AI 错误提示 -->
          <div v-else-if="msg.kind === 'error'" class="bubble error-bubble">
            <AppIcon name="alert" :size="16" /> {{ msg.text }}
          </div>

          <!-- 转写卡片 -->
          <div v-else-if="msg.kind === 'transcribe'" class="ai-card">
            <p class="ai-card-title"><AppIcon name="camera" :size="17" /> 照片转写结果</p>
            <p class="hint" style="margin-bottom: 10px">
              我先把照片里的内容转写出来，认错的地方可以直接改，确认无误后点「确认批改」。
            </p>
            <label class="mini-label">题干</label>
            <input v-model="msg.questionText" type="text" :disabled="msg.confirmed" />
            <label class="mini-label">解题步骤（每行一步，不用写题干）</label>
            <div v-for="(s, i) in msg.steps" :key="i" class="transcribe-step">
              <span class="tnum step-idx">{{ i + 1 }}</span>
              <input v-model="msg.steps[i]" type="text" :disabled="msg.confirmed" />
              <button class="icon-btn" title="删除这一步" :disabled="msg.confirmed" @click="msg.steps.splice(i, 1)">
                <AppIcon name="x" :size="16" />
              </button>
            </div>
            <button class="btn small secondary inline-icon" :disabled="msg.confirmed" @click="msg.steps.push('')">
              <AppIcon name="plus" :size="14" /> 添加一步
            </button>
            <label class="mini-label">这道题对应课本里的哪一题</label>
            <select v-model="msg.questionId" :disabled="msg.confirmed">
              <option :value="null">请选择…</option>
              <option v-for="q in allMathQuestions" :key="q.id" :value="q.id">
                {{ q.assignmentTitle }} · {{ q.stem }}
              </option>
            </select>
            <div class="toolbar" style="margin: 14px 0 0">
              <button class="btn" :disabled="msg.confirmed || msg.submitting" @click="confirmTranscribe(msg)">
                {{ msg.confirmed ? '已批改' : msg.submitting ? '批改中…' : '确认批改' }}
              </button>
            </div>
          </div>

          <!-- 诊断卡片 -->
          <div v-else-if="msg.kind === 'diagnosis' && msg.result" class="ai-card">
            <p class="ai-card-title">
              <AppIcon name="check" :size="17" /> 批改结果
              <span class="badge badge-blue">{{ questionStem(msg.result.question_id) }}</span>
            </p>
            <div
              v-for="st in msg.result.steps"
              :key="st.seq"
              class="diag-step"
              :class="{ 'first-error': st.status === 'error', correct: st.status === 'ok' }"
            >
              <span class="diag-icon" :class="st.status"><AppIcon :name="stepIcon(st.status)" :size="15" /></span>
              <div class="diag-step-main">
                <div class="step-title">{{ st.seq === 0 ? '题干' : `步骤 ${st.seq}` }} · {{ STEP_STATUS_TEXT[st.status] }}</div>
                <p>{{ st.text }}</p>
              </div>
            </div>

            <template v-if="msg.result.errors.length">
              <div v-for="e in msg.result.errors" :key="e.id" class="error-item">
                <p>
                  <ErrorTypeBadge :type="e.error_type" />
                  <span v-if="e.is_stubborn" class="badge badge-amber">需要加固的知识点</span>
                  <span v-else class="badge badge-green">已注意，继续保持</span>
                </p>
                <p class="encourage">
                  {{ e.is_stubborn ? '这个知识点还需要再加固一下，多练几道同类题会有帮助。' : '这是一次偶发的小失误，下次细心一点就好。' }}
                </p>
                <p class="detail"><strong>解析：</strong>{{ sanitizeStudentCopy(e.detail) }}</p>
                <div class="toolbar" style="margin-top: 8px; margin-bottom: 0">
                  <router-link to="/student/corrections"><button class="btn small secondary">去订正这道题</button></router-link>
                </div>
              </div>
            </template>
            <p v-else class="ok-line"><AppIcon name="check" :size="16" /> 太棒了，这道题全部正确，继续保持！</p>
          </div>

          <!-- 用户消息 -->
          <div v-else-if="msg.side === 'user' && msg.kind === 'image'" class="user-image">
            <img :src="msg.url" alt="作业照片" />
          </div>
          <div v-else-if="msg.side === 'user'" class="bubble user-bubble">{{ msg.text }}</div>
        </div>

        <div v-if="loadingInit" class="loading">正在为你准备学习简报…</div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="chat-composer">
      <div class="chat-inner composer-inner">
        <input ref="fileRef" type="file" accept="image/jpeg,image/png,image/webp" hidden @change="onFileChange" />
        <button class="icon-btn composer-btn" title="拍照 / 上传作业照片" :disabled="busy" @click="fileRef?.click()">
          <AppIcon name="camera" :size="23" />
        </button>
        <textarea
          v-model="draft"
          rows="2"
          placeholder="输入解题步骤，每行一步；也可以点相机按钮拍照批改（Enter 发送，Shift+Enter 换行）"
          @keydown.enter.exact.prevent="sendText"
        ></textarea>
        <button class="btn inline-icon send-btn" :disabled="busy || !draft.trim()" @click="sendText">
          <AppIcon name="send" :size="16" /> 发送
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useStudentStore } from '../../stores/student'
import type {
  Assignment,
  PendingAssignment,
  Question,
  StepStatus,
  StudentBriefing,
  SubmissionResult
} from '../../api/types'
import { STEP_STATUS_TEXT } from '../../api/types'
import { sanitizeStudentCopy } from '../../utils/errorType'
import AppIcon from '../../components/icons/AppIcon.vue'
import type { IconName } from '../../components/icons/paths'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'

const auth = useAuthStore()
const student = useStudentStore()

// ---------- 对话消息 ----------
interface ChatMsg {
  id: number
  side: 'ai' | 'user'
  kind: 'briefing' | 'text' | 'image' | 'transcribe' | 'diagnosis' | 'error'
  text: string
  url: string
  briefing: StudentBriefing | null
  questionText: string
  steps: string[]
  questionId: number | null
  confirmed: boolean
  submitting: boolean
  pending: boolean
  result: SubmissionResult | null
}

const messages = ref<ChatMsg[]>([])
let seq = 0
function pushMsg(partial: Partial<ChatMsg>): ChatMsg {
  const msg: ChatMsg = {
    id: ++seq,
    side: 'ai',
    kind: 'text',
    text: '',
    url: '',
    briefing: null,
    questionText: '',
    steps: [],
    questionId: null,
    confirmed: false,
    submitting: false,
    pending: false,
    result: null,
    ...partial
  }
  messages.value.push(msg)
  scrollToBottom()
  return msg
}

// ---------- 题目选择 ----------
interface FlatQuestion extends Question {
  assignmentTitle: string
}
const assignments = ref<Assignment[]>([])
const questionsByAssignment = ref<Record<number, Question[]>>({})
const flatQuestions = ref<FlatQuestion[]>([])
const assignmentId = ref<number | ''>('')
const questionId = ref<number | ''>('')
const doneQids = ref<Set<number>>(new Set())

const currentQuestions = computed(() => questionsByAssignment.value[Number(assignmentId.value)] ?? [])
const selectedQuestion = computed(
  () => flatQuestions.value.find((q) => q.id === Number(questionId.value)) ?? null
)
const allMathQuestions = computed(() => flatQuestions.value.filter((q) => q.subject === 'math'))

function onAssignmentChange() {
  const qs = currentQuestions.value
  questionId.value = qs.length ? qs[0].id : ''
}

function questionStem(qid: number): string {
  return flatQuestions.value.find((q) => q.id === qid)?.stem ?? ''
}

// ---------- 输入区 ----------
const draft = ref('')
const sending = ref(false)
const fileRef = ref<HTMLInputElement | null>(null)
const bodyRef = ref<HTMLElement | null>(null)
const loadingInit = ref(true)
const busy = computed(() => sending.value || messages.value.some((m) => m.pending))

function scrollToBottom() {
  nextTick(() => {
    const el = bodyRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function errDetail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof d === 'string' ? d : ''
}

function stepIcon(s: StepStatus): IconName {
  return { stem: 'file', ok: 'check', error: 'x', unparseable: 'help', skipped: 'minus' }[s] as IconName
}

function briefingAllDone(b: StudentBriefing): boolean {
  return (
    b.pending_assignments.length === 0 &&
    b.pending_corrections_count === 0 &&
    b.weak_points.length === 0
  )
}

// 简报「去完成」：选中该作业里第一道还没做的数学题（没有数学题则选第一道未做题）
async function gotoAssignment(p: PendingAssignment) {
  assignmentId.value = p.id
  const qs = currentQuestions.value
  const target =
    qs.find((q) => !doneQids.value.has(q.id) && q.subject === 'math') ??
    qs.find((q) => !doneQids.value.has(q.id)) ??
    qs[0]
  questionId.value = target ? target.id : ''
  if (target?.subject === 'english') {
    pushMsg({
      side: 'ai',
      kind: 'text',
      text: `已帮你选中《${p.title}》的作文题，作文请到「交作业」页粘贴全文提交批改。`
    })
  } else if (target) {
    pushMsg({
      side: 'ai',
      kind: 'text',
      text: `已帮你选中《${p.title}》的题目「${target.stem}」，把解题步骤按行输入发送给我，或者点相机按钮拍照批改。`
    })
  }
  scrollToBottom()
}

// ---------- 文本批改 ----------
async function sendText() {
  const lines = draft.value.split('\n').map((s) => s.trim()).filter(Boolean)
  if (!lines.length || busy.value) return
  if (!selectedQuestion.value) {
    pushMsg({ side: 'ai', kind: 'error', text: '先在上方选择要批改的作业和题目，再把步骤发给我。' })
    return
  }
  pushMsg({ side: 'user', kind: 'text', text: lines.join('\n') })
  draft.value = ''
  if (selectedQuestion.value.subject === 'english') {
    pushMsg({
      side: 'ai',
      kind: 'text',
      text: '这是作文题，步骤批改只支持数学题。作文请到左侧「交作业」页粘贴全文提交，我会从内容、结构、语法、词汇、表达五个方面帮你打分。'
    })
    return
  }
  sending.value = true
  try {
    const res = await student.submitMath({ question_id: selectedQuestion.value.id, steps: lines })
    doneQids.value.add(selectedQuestion.value.id)
    pushMsg({ side: 'ai', kind: 'diagnosis', result: res })
  } catch (e) {
    pushMsg({ side: 'ai', kind: 'error', text: '批改失败：' + (errDetail(e) || '请稍后重试。') })
    console.error(e)
  } finally {
    sending.value = false
    scrollToBottom()
  }
}

// ---------- 拍照批改 ----------
async function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    pushMsg({ side: 'ai', kind: 'error', text: '这张图片格式不对，请上传 jpg / png / webp 格式的作业照片。' })
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    pushMsg({ side: 'ai', kind: 'error', text: '图片太大了（超过 10MB），请压缩后再试。' })
    return
  }
  pushMsg({ side: 'user', kind: 'image', url: URL.createObjectURL(file) })
  const wait = pushMsg({ side: 'ai', kind: 'text', text: '正在识别照片里的解题步骤…', pending: true })
  try {
    const res = await student.transcribePhoto(file)
    wait.kind = 'transcribe'
    wait.pending = false
    wait.text = ''
    wait.questionText = res.question_text
    wait.steps = [...res.steps]
    wait.questionId =
      selectedQuestion.value?.subject === 'math'
        ? selectedQuestion.value.id
        : (allMathQuestions.value[0]?.id ?? null)
  } catch (err) {
    wait.kind = 'error'
    wait.pending = false
    wait.text = '识别失败：' + (errDetail(err) || '请稍后重试。')
    console.error(err)
  }
  scrollToBottom()
}

async function confirmTranscribe(msg: ChatMsg) {
  const steps = msg.steps.map((s) => s.trim()).filter(Boolean)
  if (!steps.length) {
    pushMsg({ side: 'ai', kind: 'error', text: '转写卡片里的步骤是空的，先补上步骤再确认批改。' })
    return
  }
  if (!msg.questionId) {
    pushMsg({ side: 'ai', kind: 'error', text: '请先在转写卡片里选择这道题对应课本里的哪一题。' })
    return
  }
  msg.submitting = true
  try {
    const res = await student.submitMath({ question_id: msg.questionId, steps })
    msg.confirmed = true
    doneQids.value.add(msg.questionId)
    pushMsg({ side: 'ai', kind: 'diagnosis', result: res })
  } catch (e) {
    pushMsg({ side: 'ai', kind: 'error', text: '批改失败：' + (errDetail(e) || '请稍后重试。') })
    console.error(e)
  } finally {
    msg.submitting = false
    scrollToBottom()
  }
}

// ---------- 初始化 ----------
onMounted(async () => {
  try {
    const [list, subs, essays] = await Promise.all([
      student.fetchAssignments(),
      student.fetchMySubmissions().catch(() => []),
      student.fetchMyEssays().catch(() => [])
    ])
    assignments.value = list
    subs.forEach((s) => doneQids.value.add(s.question_id))
    essays.forEach((s) => {
      if (s.question_id) doneQids.value.add(s.question_id)
    })
    const details = await Promise.all(list.map((a) => student.fetchAssignmentDetail(a.id)))
    details.forEach((d) => {
      questionsByAssignment.value[d.id] = d.questions
      d.questions.forEach((q) => flatQuestions.value.push({ ...q, assignmentTitle: d.title }))
    })
    // 默认选中第一份作业的第一道题，减少文本批改的操作成本
    if (list.length) {
      assignmentId.value = list[0].id
      onAssignmentChange()
    }
  } catch (e) {
    pushMsg({ side: 'ai', kind: 'error', text: '作业数据加载失败，请确认后端已启动后刷新页面。' })
    console.error(e)
  }
  try {
    const briefing = await student.fetchBriefing()
    // 简报作为第一条 AI 消息
    messages.value.unshift({
      id: ++seq,
      side: 'ai',
      kind: 'briefing',
      text: '',
      url: '',
      briefing,
      questionText: '',
      steps: [],
      questionId: null,
      confirmed: false,
      submitting: false,
      pending: false,
      result: null
    })
  } catch (e) {
    pushMsg({ side: 'ai', kind: 'error', text: '学习简报加载失败，刷新页面可以重试。' })
    console.error(e)
  } finally {
    loadingInit.value = false
    scrollToBottom()
  }
})
</script>

<style scoped>
.chat-layout { display: flex; flex-direction: column; height: 100dvh; background: var(--bg); }
.chat-inner { max-width: 860px; width: 100%; margin: 0 auto; padding: 0 20px; }
.chat-header { background: var(--card); border-bottom: 1px solid var(--border); padding: 14px 0; }
.chat-title { display: flex; align-items: center; gap: 8px; font-size: 17px; font-weight: 700; color: var(--primary); }
.chat-title .hint { font-weight: 400; }
.chat-selectors { display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
.chat-selectors select { flex: 1 1 240px; width: auto; }
.chat-header .hint { margin-top: 8px; }

.chat-body { flex: 1; overflow-y: auto; padding: 20px 0 24px; }
.msg-row { display: flex; gap: 10px; margin-bottom: 16px; align-items: flex-start; }
.msg-row.user { flex-direction: row-reverse; }
.msg-avatar {
  width: 30px; height: 30px; border-radius: 50%;
  background: var(--primary-50); color: var(--primary);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 2px;
}
.bubble { border-radius: 14px; padding: 11px 16px; font-size: 14.5px; max-width: 78%; white-space: pre-wrap; word-break: break-word; }
.ai-bubble { background: var(--card); border: 1px solid #EDF0F4; box-shadow: var(--shadow); display: inline-flex; align-items: center; gap: 8px; }
.error-bubble { background: var(--red-bg); color: #991B1B; display: inline-flex; align-items: center; gap: 8px; }
.user-bubble { background: var(--primary); color: #fff; }
.user-image img { max-width: 320px; max-height: 380px; border-radius: 12px; border: 1px solid var(--border); display: block; }

.ai-card {
  background: var(--card); border: 1px solid #EDF0F4; border-radius: 14px;
  box-shadow: var(--shadow); padding: 16px 18px; width: min(660px, 100%);
}
.ai-card-title { font-size: 15px; font-weight: 700; display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.brief-section { margin-top: 12px; }
.brief-label { font-size: 13px; font-weight: 600; color: var(--text-2); margin-bottom: 6px; }
.brief-item { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 0; border-bottom: 1px solid #F1F3F6; }
.brief-item:last-child { border-bottom: none; }
.brief-item-main { font-size: 14.5px; }
.brief-line { font-size: 14.5px; }
.review-tip { margin-top: 10px; background: var(--primary-50); border-radius: 8px; padding: 10px 14px; font-size: 14px; }

.mini-label { display: block; font-size: 13px; color: var(--text-2); margin: 12px 0 6px; }
.transcribe-step { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.transcribe-step .step-idx { min-width: 20px; text-align: right; color: var(--text-3); font-size: 13px; }

.diag-step {
  display: flex; gap: 10px;
  border: 1px solid var(--border); border-left: 4px solid #D1D5DB;
  border-radius: 8px; padding: 10px 14px; margin-bottom: 8px; background: #fff;
}
.diag-step.first-error { border-left-color: var(--red); background: #FFFBFB; }
.diag-step.correct { border-left-color: var(--green); }
.diag-icon { width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex-shrink: 0; background: var(--gray-bg); color: var(--gray); }
.diag-icon.ok { background: var(--green-bg); color: var(--green); }
.diag-icon.error { background: var(--red-bg); color: var(--red); }
.diag-icon.unparseable { background: var(--amber-bg); color: var(--amber); }
.diag-step-main { flex: 1; min-width: 0; }
.diag-step .step-title { font-weight: 600; font-size: 13px; color: var(--text-3); margin-bottom: 2px; }
.diag-step.first-error .step-title { color: #991B1B; }
.diag-step.correct .step-title { color: #065F46; }
.error-item { margin-top: 14px; padding-top: 12px; border-top: 1px solid #F1F3F6; }
.encourage { margin-top: 8px; font-size: 14px; }
.detail { margin-top: 6px; font-size: 14px; color: var(--text-2); }
.ok-line { margin-top: 10px; font-size: 14.5px; color: #065F46; display: flex; align-items: center; gap: 6px; }

.chat-composer { background: var(--card); border-top: 1px solid var(--border); padding: 12px 0 16px; }
.composer-inner { display: flex; gap: 10px; align-items: flex-end; }
.composer-inner textarea { flex: 1; min-height: 48px; max-height: 140px; }
.composer-btn { padding: 10px; color: var(--primary); }
.composer-btn:disabled { color: var(--text-3); cursor: not-allowed; }
.send-btn { padding: 11px 22px; }
.spin { animation: chat-spin 1s linear infinite; }
@keyframes chat-spin { to { transform: rotate(360deg); } }

@media (max-width: 960px) {
  .chat-layout { height: calc(100dvh - 52px); }
  .user-image img { max-width: 240px; }
  .bubble { max-width: 88%; }
}
</style>
