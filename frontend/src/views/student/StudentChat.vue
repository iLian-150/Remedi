<!-- 学生端：智能批改（对话页，学生登录默认落地页）
     v0.2.0：打开先播报首页简报（GET /api/student/briefing）；拍照转写 → 确认 → 诊断。
     v0.2.1：简报改为卡片区（大数字 + 色块标签）；作答以拍照为主，线上文本输入步骤已下线。
     v0.6.2：会话导航移入左侧栏（ChatGPT 式），本页只管消息流；底部输入区改悬浮毛玻璃卡。
     文案伦理沿用学生端口径：不出现「顽固」「置信度」等术语（与既有页面一致）。 -->
<template>
  <div class="chat-layout">
    <!-- 顶部：题目选择器（仅数学题，拍照批改的归属题目） -->
    <div class="chat-header">
      <div class="chat-inner">
        <div class="chat-title">
          <AppIcon name="sparkles" :size="20" />
          <span>智能批改</span>
          <span class="hint">拍一张作业照片，老师会逐步帮你检查；也可以直接打字问我问题</span>
        </div>
        <div class="chat-selectors">
          <select v-model="assignmentId" @change="onAssignmentChange" aria-label="选择作业">
            <option value="">选择作业…</option>
            <option v-for="a in assignments" :key="a.id" :value="a.id">{{ a.title }}</option>
          </select>
          <select v-model="questionId" :disabled="!currentQuestions.length" aria-label="选择题目">
            <option value="">选择题目…</option>
            <option v-for="q in currentQuestions" :key="q.id" :value="q.id">
              [{{ q.knowledge_point }}] {{ q.stem }}
            </option>
          </select>
        </div>
      </div>
    </div>

    <!-- 消息流 -->
    <div class="chat-body" ref="bodyRef">
      <div class="chat-inner">
        <div v-for="msg in messages" :key="msg.id" class="msg-row" :class="msg.side">
          <div v-if="msg.side === 'ai'" class="msg-avatar"><AppIcon name="sparkles" :size="16" /></div>

          <!-- AI 简报卡片区（v0.2.1 卡片化） -->
          <div v-if="msg.kind === 'briefing' && msg.briefing" class="ai-card briefing-card">
            <p class="ai-card-title"><AppIcon name="clipboard" :size="17" /> 学习简报</p>

            <!-- 全部完成：鼓励卡 -->
            <div v-if="briefingAllDone(msg.briefing)" class="brief-done">
              <span class="brief-done-icon"><AppIcon name="check" :size="22" /></span>
              <div>
                <p class="brief-done-title">太棒了，{{ auth.name }}！全部完成</p>
                <p class="brief-done-line">
                  作业都做完了，订正也全部搞定，暂时没有需要加固的知识点。复习建议：遮住答案把最近的题目独立重做一遍，巩固手感。
                </p>
              </div>
            </div>

            <template v-else>
              <p class="brief-hello">{{ auth.name }}，你好！这是你现在的进度：</p>

              <div class="brief-grid">
                <!-- 未完成作业卡 -->
                <div v-if="msg.briefing.pending_assignments.length" class="brief-stat-card brief-assign">
                  <div class="brief-stat-head">
                    <span class="brief-big tnum">{{ msg.briefing.pending_assignments.length }}</span>
                    <span class="brief-stat-label">份作业还没完成</span>
                  </div>
                  <div v-for="p in msg.briefing.pending_assignments" :key="p.id" class="brief-item">
                    <span class="brief-item-main">
                      {{ p.title }}
                      <span v-if="p.mode === 'offline'" class="badge badge-amber">线下练习</span>
                      <span class="badge badge-blue tnum">还剩 {{ p.remaining_count }} 题</span>
                      <span v-if="p.mode === 'offline'" class="brief-item-sub">
                        <template v-if="p.workbook_title">{{ p.workbook_title }}</template>
                        <template v-if="p.page_range"> · {{ p.page_range }}</template>
                        <template v-if="p.deadline"> · 截止 {{ fmtDateTime(p.deadline) }}</template>
                      </span>
                    </span>
                    <button class="btn small" @click="gotoAssignment(p)">去完成</button>
                  </div>
                </div>

                <!-- 待订正卡 -->
                <div v-if="msg.briefing.pending_corrections_count" class="brief-stat-card brief-corr">
                  <div class="brief-stat-head">
                    <span class="brief-big tnum">{{ msg.briefing.pending_corrections_count }}</span>
                    <span class="brief-stat-label">处错题还没订正</span>
                  </div>
                  <p class="brief-one-line" v-if="msg.briefing.pending_corrections_knowledge_points.length">
                    涉及知识点：{{ msg.briefing.pending_corrections_knowledge_points.join('、') }}
                  </p>
                  <router-link to="/student/corrections"><button class="btn small secondary">去订正</button></router-link>
                </div>
              </div>

              <!-- 需加固知识点小卡 -->
              <div v-if="briefWeakDetails(msg.briefing).length" class="brief-weak">
                <p class="brief-label">需要加固的知识点</p>
                <div class="brief-weak-grid">
                  <div v-for="d in briefWeakDetails(msg.briefing)" :key="d.knowledge_point" class="brief-weak-card">
                    <span class="brief-weak-name">{{ d.knowledge_point }}</span>
                    <span class="brief-weak-meta">
                      出错 <span class="tnum">{{ d.error_count }}</span> 次
                      <template v-if="d.last_error_at"> · 最近 {{ fmtDate(d.last_error_at) }}</template>
                    </span>
                  </div>
                </div>
              </div>

              <!-- 最近动态：一行小字 -->
              <p v-if="msg.briefing.recent_feedback" class="brief-recent">
                最近动态：{{ sanitizeStudentCopy(msg.briefing.recent_feedback) }}
              </p>
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

            <!-- 追问（v0.4.0）：先想一想，再看解析 -->
            <div v-if="msg.result.follow_up_question" class="followup-box">
              <span class="followup-icon"><AppIcon name="lightbulb" :size="16" /></span>
              <p><b>想一想：</b>{{ msg.result.follow_up_question }}</p>
            </div>
          </div>

          <!-- 用户消息 -->
          <div v-else-if="msg.side === 'user' && msg.kind === 'image'" class="user-image">
            <img :src="msg.url" alt="作业照片" />
          </div>
          <div v-else-if="msg.side === 'user'" class="bubble user-bubble">{{ msg.text }}</div>
        </div>

        <!-- 建议气泡（v0.6.0）：只挂最新一轮对话回复，stagger 淡入上浮，点击直接发送 -->
        <div v-if="suggestions.length && !chatSending" class="suggest-row">
          <button
            v-for="(s, i) in suggestions"
            :key="s"
            class="suggest-chip"
            :style="{ animationDelay: `${i * 70}ms` }"
            @click="sendChat(s)"
          >
            {{ s }}
          </button>
        </div>

        <div v-if="loadingInit" class="loading">正在为你准备学习简报…</div>
      </div>
    </div>

    <!-- 输入区（v0.3.0：文本聊天接学习助手 Agent + 拍照批改并存；
         v0.6.2：改悬浮卡片——毛玻璃卡离底悬浮，消息从卡下滚过；输入框无边框融入卡内，
         拍照与发送收成卡内右侧的圆形按钮，聚焦时卡片带主色光晕） -->
    <div class="chat-composer">
      <div class="chat-inner">
        <div class="composer-card">
          <p class="composer-tip">可以问我数学问题，也可以问问你的学习情况</p>
          <div class="composer-row">
            <input ref="fileRef" type="file" accept="image/jpeg,image/png,image/webp" hidden @change="onFileChange" />
            <input
              v-model="chatInput"
              class="chat-text-input"
              type="text"
              placeholder="输入你的问题，回车发送"
              :disabled="chatSending"
              @keyup.enter="sendChat()"
            />
            <button
              class="composer-circle photo-circle"
              title="拍照批改"
              :disabled="busy"
              @click="fileRef?.click()"
            >
              <AppIcon name="camera" :size="19" />
            </button>
            <button
              class="composer-circle send-circle"
              title="发送"
              :disabled="chatSending || !chatInput.trim()"
              @click="sendChat()"
            >
              <AppIcon name="send" :size="17" />
            </button>
          </div>
          <p class="composer-hint">
            点相机拍一张作业照片，老师会逐步帮你批改<template v-if="selectedQuestion">（当前题目：{{ selectedQuestion.stem }}）</template>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import { useStudentStore } from '../../stores/student'
import type {
  Assignment,
  PendingAssignment,
  Question,
  StepStatus,
  StudentBriefing,
  SubmissionResult,
  WeakPointDetail
} from '../../api/types'
import { STEP_STATUS_TEXT } from '../../api/types'
import { sanitizeStudentCopy } from '../../utils/errorType'
import AppIcon from '../../components/icons/AppIcon.vue'
import type { IconName } from '../../components/icons/paths'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'

const auth = useAuthStore()
const student = useStudentStore()
const route = useRoute()

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

// ---------- 题目选择（仅数学题可拍照批改） ----------
interface FlatQuestion extends Question {
  assignmentTitle: string
}
const assignments = ref<Assignment[]>([])
const questionsByAssignment = ref<Record<number, Question[]>>({})
const flatQuestions = ref<FlatQuestion[]>([])
const assignmentId = ref<number | ''>('')
const questionId = ref<number | ''>('')
const doneQids = ref<Set<number>>(new Set())

const currentQuestions = computed(
  () => (questionsByAssignment.value[Number(assignmentId.value)] ?? []).filter((q) => q.subject === 'math')
)
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
const fileRef = ref<HTMLInputElement | null>(null)
const bodyRef = ref<HTMLElement | null>(null)
const loadingInit = ref(true)
const busy = computed(() => messages.value.some((m) => m.pending || m.submitting))

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

function fmtDate(t: string): string {
  return t.replace('T', ' ').slice(0, 10)
}
function fmtDateTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

// ---------- 简报 ----------
function briefingAllDone(b: StudentBriefing): boolean {
  return (
    b.pending_assignments.length === 0 &&
    b.pending_corrections_count === 0 &&
    b.weak_points.length === 0
  )
}

/** 需加固知识点明细：优先用后端 weak_point_details，缺失时用 weak_points 名称兜底 */
function briefWeakDetails(b: StudentBriefing): WeakPointDetail[] {
  if (b.weak_point_details?.length) return b.weak_point_details
  return b.weak_points.map((kp) => ({ knowledge_point: kp, error_count: 0, last_error_at: null }))
}

// 简报「去完成」：选中该作业里第一道还没做的数学题，并引导拍照
async function gotoAssignment(p: PendingAssignment) {
  assignmentId.value = p.id
  const qs = currentQuestions.value
  const target = qs.find((q) => !doneQids.value.has(q.id)) ?? qs[0]
  questionId.value = target ? target.id : ''
  if (target) {
    pushMsg({
      side: 'ai',
      kind: 'text',
      text: `已帮你选中《${p.title}》的题目「${target.stem}」，点下方「拍照批改」，拍下你的作答过程就可以啦。`
    })
  }
  scrollToBottom()
}

// ---------- 学习助手文本聊天（v0.3.0：LangGraph Agent） ----------
const chatInput = ref('')
const chatSending = ref(false)

// ---------- 会话（v0.6.0 会话制；v0.6.2 导航移入左侧栏，会话状态归 store 与侧栏共用） ----------
// 本页不再持有会话列表：侧栏点新对话/切换/删除当前会话时改 store.sessionView，
// 本页 watch 到 seq 变化后同步重渲染消息区；发送消息后回写 activeSessionId 并刷新侧栏列表。
// ---------- 建议气泡（v0.6.0）：只存最新一轮回复的建议 ----------
const suggestions = ref<string[]>([])

/** 把简报卡作为第一条消息放回对话区（新对话/切换会话后复用） */
async function prependBriefing() {
  try {
    const briefing = await student.fetchBriefing()
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
    console.error(e)
  }
}

/** 把某条会话的历史消息渲染进消息区：简报卡保留置顶，其余消息替换为该会话的记录 */
async function renderSessionMessages(id: number) {
  try {
    const rows = await student.fetchSessionMessages(id)
    messages.value = messages.value.filter((m) => m.kind === 'briefing')
    rows.forEach((h) =>
      pushMsg({ side: h.role === 'user' ? 'user' : 'ai', kind: 'text', text: h.content })
    )
    scrollToBottom()
  } catch (e) {
    pushMsg({ side: 'ai', kind: 'error', text: '打开这条对话失败：' + (errDetail(e) || '请稍后重试。') })
    console.error(e)
  }
}

// 侧栏会话操作（新对话 / 切换 / 删除当前会话）统一改 store.sessionView，
// seq 递增时本页在此同步重渲染，保证侧栏与对话页永远一致。
let appliedViewSeq = 0
watch(
  () => student.sessionView.seq,
  async (seq) => {
    if (seq === appliedViewSeq) return
    appliedViewSeq = seq
    const view = student.sessionView
    suggestions.value = []
    if (view.fresh) {
      messages.value = []
      await prependBriefing()
      pushMsg({
        side: 'ai',
        kind: 'text',
        text: '已开始新对话。之前的对话都收在左侧栏里，点任意一条标题就能接着聊。'
      })
    } else if (view.id != null) {
      await renderSessionMessages(view.id)
    } else {
      // 会话全删光了：只留简报卡，回到空白态
      messages.value = messages.value.filter((m) => m.kind === 'briefing')
    }
    scrollToBottom()
  }
)

async function sendChat(raw?: string) {
  const text = (typeof raw === 'string' ? raw : chatInput.value).trim()
  if (!text || chatSending.value) return
  if (text.length > 2000) {
    pushMsg({ side: 'ai', kind: 'error', text: '这条消息有点太长了（最多 2000 字），拆成两条发给我吧。' })
    return
  }
  chatInput.value = ''
  suggestions.value = []
  pushMsg({ side: 'user', kind: 'text', text })
  const wait = pushMsg({ side: 'ai', kind: 'text', text: '正在思考…', pending: true })
  chatSending.value = true
  try {
    const res = await student.agentChat(text, student.activeSessionId)
    wait.text = res.reply
    if (res.session_id) student.setActiveSession(res.session_id)
    suggestions.value = res.suggestions ?? []
    // 刷新侧栏会话列表（v0.6.2）：首问会生成标题，顺序也按最近更新重排
    student.loadSessions(true)
  } catch (e) {
    wait.kind = 'error'
    wait.text = '发送失败：' + (errDetail(e) || '请稍后重试。')
    console.error(e)
  } finally {
    wait.pending = false
    chatSending.value = false
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
    const [list, subs] = await Promise.all([
      student.fetchAssignments(),
      student.fetchMySubmissions().catch(() => [])
    ])
    assignments.value = list
    subs.forEach((s) => doneQids.value.add(s.question_id))
    const details = await Promise.all(list.map((a) => student.fetchAssignmentDetail(a.id)))
    details.forEach((d) => {
      questionsByAssignment.value[d.id] = d.questions
      d.questions.forEach((q) => flatQuestions.value.push({ ...q, assignmentTitle: d.title }))
    })
    // 预选：优先用路由参数（简报/交作业页带过来），否则默认第一份作业的第一道数学题
    const presetAssignment = Number(route.query.assignment_id)
    const presetQuestion = Number(route.query.question_id)
    if (presetAssignment && questionsByAssignment.value[presetAssignment]) {
      assignmentId.value = presetAssignment
      const qs = currentQuestions.value
      questionId.value = qs.some((q) => q.id === presetQuestion)
        ? presetQuestion
        : (qs.find((q) => !doneQids.value.has(q.id))?.id ?? qs[0]?.id ?? '')
    } else if (list.length) {
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
  }
  // 历史对话接在简报下方（v0.3.0：GET agent/history；v0.6.0 起为当前会话的消息）
  try {
    const history = await student.fetchAgentHistory()
    history.forEach((h) =>
      pushMsg({ side: h.role === 'user' ? 'user' : 'ai', kind: 'text', text: h.content })
    )
  } catch (e) {
    console.error(e)
  }
  // 当前会话定位（v0.6.2）：会话状态归 store 与侧栏共用，列表第一条即当前会话；
  // appliedViewSeq 对齐当前值，避免把挂载前产生的查看请求误当新切换重渲染
  await student.loadSessions()
  appliedViewSeq = student.sessionView.seq
  loadingInit.value = false
  scrollToBottom()
})
</script>

<style scoped>
.chat-layout { display: flex; flex-direction: column; height: 100dvh; background: var(--bg); position: relative; }
.chat-inner { max-width: 860px; width: 100%; margin: 0 auto; padding: 0 20px; }
.chat-header { background: var(--card); border-bottom: 1px solid var(--border); padding: 14px 0; }
.chat-title { display: flex; align-items: center; gap: 8px; font-size: 17px; font-weight: 700; color: var(--primary); }
.chat-title .hint { font-weight: 400; }

/* 建议气泡（v0.6.0）：只挂最新一轮回复，淡入上浮 stagger */
.suggest-row { display: flex; gap: 8px; flex-wrap: wrap; margin: -4px 0 16px 40px; }
.suggest-chip {
  border: 1px solid #D7E3FA;
  background: linear-gradient(135deg, #FFFFFF 0%, #EFF5FF 100%);
  color: var(--primary);
  border-radius: 999px; padding: 6px 13px; font-size: 13px; font-weight: 600;
  cursor: pointer; font-family: var(--font);
  animation: suggest-in 0.35s ease both;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.suggest-chip:hover { transform: translateY(-1px); box-shadow: var(--shadow); }
@keyframes suggest-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
.brief-item-sub { display: block; font-size: 12.5px; color: var(--text-2); margin-top: 2px; }
.chat-selectors { display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
.chat-selectors select { flex: 1 1 240px; width: auto; }

/* 底部留白加大：给悬浮输入卡让位，最后的消息不被卡片遮住 */
.chat-body { flex: 1; overflow-y: auto; padding: 20px 0 184px; }
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

/* 简报卡片区（v0.2.1 卡片化；v0.4.0 放宽卡宽，统计卡真正横向并排） */
.briefing-card { width: min(820px, 100%); }
.brief-hello { font-size: 14.5px; margin-bottom: 12px; }
.brief-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.brief-stat-card { border-radius: 12px; padding: 14px 16px; border: 1px solid #EDF0F4; }
.brief-assign { background: var(--primary-50); }
.brief-corr { background: #FFFBEB; }
.brief-stat-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
.brief-big { font-size: 30px; font-weight: 800; line-height: 1.1; color: var(--primary); }
.brief-corr .brief-big { color: var(--amber); }
.brief-stat-label { font-size: 13.5px; font-weight: 600; color: var(--text-2); }
.brief-one-line { font-size: 13px; color: var(--text-2); margin-bottom: 10px; }
.brief-item { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 0; border-top: 1px solid rgba(29, 78, 216, 0.12); }
.brief-item-main { font-size: 14px; }
.brief-label { font-size: 13px; font-weight: 600; color: var(--text-2); margin-bottom: 8px; }
.brief-weak { margin-top: 14px; }
.brief-weak-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px; }
.brief-weak-card {
  background: var(--amber-bg); border-radius: 10px; padding: 10px 12px;
  display: flex; flex-direction: column; gap: 2px;
}
.brief-weak-name { font-size: 14px; font-weight: 700; color: #92400E; }
.brief-weak-meta { font-size: 12px; color: #92400E; opacity: 0.85; }
.brief-recent { margin-top: 14px; font-size: 13px; color: var(--text-2); border-top: 1px solid #F1F3F6; padding-top: 10px; }
.brief-done { display: flex; gap: 12px; background: var(--green-bg); border-radius: 12px; padding: 14px 16px; }
.brief-done-icon {
  width: 40px; height: 40px; border-radius: 50%; flex-shrink: 0;
  background: var(--green); color: #fff;
  display: flex; align-items: center; justify-content: center;
}
.brief-done-title { font-size: 15.5px; font-weight: 700; color: #065F46; margin-bottom: 2px; }
.brief-done-line { font-size: 13.5px; color: #065F46; }

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
.followup-box {
  display: flex; gap: 9px; align-items: flex-start;
  background: var(--primary-50); border: 1px solid #DBEAFE; border-radius: 10px;
  padding: 11px 14px; margin-top: 14px; font-size: 14px;
}
.followup-icon {
  width: 26px; height: 26px; border-radius: 50%; flex-shrink: 0;
  background: var(--primary); color: #fff;
  display: flex; align-items: center; justify-content: center;
}
.followup-box p { padding-top: 3px; }

/* 悬浮输入卡（v0.6.2）：离底悬浮的毛玻璃卡，滚动内容从卡下透过去；
   输入框无边框融入卡内，拍照/发送是卡内右侧圆形钮，聚焦时卡带主色光晕 */
.chat-composer {
  position: absolute; left: 0; right: 0; bottom: 0; z-index: 30;
  padding: 10px 20px 16px; pointer-events: none;
}
.composer-card {
  pointer-events: auto;
  background: rgba(255, 255, 255, 0.86);
  -webkit-backdrop-filter: blur(14px) saturate(1.4);
  backdrop-filter: blur(14px) saturate(1.4);
  border: 1px solid #E2E9F5; border-radius: 20px;
  box-shadow: 0 14px 36px rgba(15, 23, 42, 0.13), 0 2px 8px rgba(15, 23, 42, 0.06);
  padding: 12px 14px 10px;
  transition: box-shadow 0.25s ease, border-color 0.25s ease;
}
.composer-card:focus-within {
  border-color: #B9CFF7;
  box-shadow: 0 14px 36px rgba(15, 23, 42, 0.13), 0 0 0 3px rgba(29, 78, 216, 0.14);
}
.composer-tip { font-size: 12.5px; color: var(--text-2); margin: 0 4px 8px; }
.composer-row { display: flex; gap: 8px; align-items: center; }
.chat-text-input {
  flex: 1; min-width: 0; padding: 10px 6px; font-size: 15px;
  border: none; background: transparent; box-shadow: none;
}
.chat-text-input:focus { border: none; box-shadow: none; outline: none; }
.composer-circle {
  width: 42px; height: 42px; border-radius: 50%; flex-shrink: 0;
  display: inline-flex; align-items: center; justify-content: center;
  cursor: pointer; font-family: var(--font);
  transition: transform 0.2s ease, box-shadow 0.2s ease, background 0.2s ease, opacity 0.2s ease;
}
.composer-circle:disabled { opacity: 0.45; cursor: not-allowed; }
.photo-circle { background: rgba(255, 255, 255, 0.7); border: 1px solid #D7E0F0; color: var(--primary); }
.photo-circle:hover:not(:disabled) { background: #fff; transform: scale(1.06); }
.send-circle {
  background: var(--primary); border: 1px solid var(--primary); color: #fff;
  box-shadow: 0 4px 12px rgba(29, 78, 216, 0.35);
}
.send-circle:hover:not(:disabled) { transform: scale(1.07); box-shadow: 0 6px 16px rgba(29, 78, 216, 0.42); }
.composer-hint { font-size: 12.5px; color: var(--text-3); margin: 8px 4px 0; }
.spin { animation: chat-spin 1s linear infinite; }
@keyframes chat-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .suggest-chip { animation: none; transition: none; }
  .composer-card, .composer-circle { transition: none; }
  .photo-circle:hover:not(:disabled), .send-circle:hover:not(:disabled) { transform: none; }
}

@media (max-width: 960px) {
  .chat-layout { height: calc(100dvh - 52px); }
  .user-image img { max-width: 240px; }
  .bubble { max-width: 88%; }
  .chat-composer { padding: 8px 12px 12px; }
  .composer-card { border-radius: 18px; }
  .chat-body { padding-bottom: 190px; }
}
</style>
