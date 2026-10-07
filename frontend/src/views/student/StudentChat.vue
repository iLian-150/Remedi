<!-- 学生端学习助手首页：新对话显示欢迎页和学习进度；开始对话后切换到消息流。
     保留 Remedi 蓝色视觉、作业拍照批改、文字问答和错题本收录。
     v0.8.1 合并修复：会话改走 store 状态层（watch sessionView 同步），
     输入区恢复 v0.6.2 的悬浮毛玻璃卡（原弹层式历史面板与页面自持会话状态已移除）。
     v0.8.2：页内侧栏整套删除——导航与会话区统一由 App.vue 全局侧栏承载
     （全局侧栏在对话页挂 SidebarSessions），本页回归普通内容布局。 -->
<template>
  <div class="chat-layout">
    <!-- 顶部：智能批改标题（会话操作在左侧栏会话区，v0.8.1） -->
    <div class="chat-header">
      <div class="chat-inner">
        <div class="chat-title">
          <span class="chat-title-mark"><AppIcon name="sparkles" :size="17" /></span>
          <span class="chat-title-copy">
            <strong>Remedi 学习助手</strong>
            <small>作业批改 · 错题复习 · 学习问答</small>
          </span>
          <span class="chat-status"><i></i> 随时可以提问</span>
        </div>
      </div>
    </div>

    <div class="chat-content-shell" :class="{ 'welcome-mode': isWelcomeScreen }">
    <!-- 消息流 / AI 首页 -->
    <div class="chat-body" :class="{ 'chat-body-welcome': isWelcomeScreen }" ref="bodyRef">
      <div class="chat-inner">
        <section v-if="isWelcomeScreen" class="welcome-home">
          <div class="welcome-kicker">今日学习</div>
          <h1>{{ auth.name || '同学' }}，今天想聊点什么？</h1>
          <p class="welcome-description">学习中遇到的问题、作业批改或错题复习，都可以在这里聊。</p>

          <div v-if="welcomeBriefing" class="welcome-briefing">
            <div class="welcome-briefing-heading">
              <span class="welcome-briefing-icon"><AppIcon name="clipboard" :size="16" /></span>
              <div><strong>学习简报</strong><small>根据你的作业和订正情况整理</small></div>
            </div>

            <div v-if="briefingAllDone(welcomeBriefing)" class="welcome-briefing-done">
              <span class="welcome-done-mark"><AppIcon name="check" :size="17" /></span>
              <div>
                <strong>太棒了，{{ auth.name }}！全部完成</strong>
                <p>作业和订正都完成了，暂时没有需要加固的知识点。可以把最近的题目独立重做一遍，巩固一下。</p>
              </div>
            </div>

            <template v-else>
              <div class="welcome-briefing-stats">
                <div><b>{{ welcomeBriefing.pending_assignments.length }}</b><span>份作业待完成</span></div>
                <div><b>{{ welcomeBriefing.pending_corrections_count }}</b><span>处错题待订正</span></div>
                <router-link to="/student/mistakes">打开错题本 <AppIcon name="chevron-right" :size="13" /></router-link>
              </div>
              <div v-if="welcomeBriefing.pending_assignments.length" class="welcome-briefing-assignments">
                <div v-for="p in welcomeBriefing.pending_assignments.slice(0, 2)" :key="p.id" class="welcome-briefing-assignment">
                  <span><strong>{{ p.title }}</strong><small>还剩 {{ p.remaining_count }} 题<template v-if="p.deadline"> · 截止 {{ fmtDateTime(p.deadline) }}</template></small></span>
                  <button type="button" @click="gotoAssignment(p)">继续 <AppIcon name="chevron-right" :size="13" /></button>
                </div>
              </div>
              <p v-if="welcomeBriefing.pending_corrections_count && welcomeBriefing.pending_corrections_knowledge_points.length" class="welcome-briefing-feedback">待订正知识点：{{ welcomeBriefing.pending_corrections_knowledge_points.join('、') }}</p>
              <div v-if="briefWeakDetails(welcomeBriefing).length" class="welcome-briefing-weak">
                <span>近期关注</span>
                <span v-for="d in briefWeakDetails(welcomeBriefing).slice(0, 3)" :key="d.knowledge_point">{{ d.knowledge_point }} · {{ d.error_count }} 次</span>
              </div>
              <p v-if="welcomeBriefing.recent_feedback" class="welcome-briefing-feedback">{{ sanitizeStudentCopy(welcomeBriefing.recent_feedback) }}</p>
            </template>
          </div>
        </section>

        <template v-else>
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
            <div v-if="msg.captureId" class="photo-capture-action">
              <span v-if="msg.saved">已加入错题本</span>
              <button v-else class="btn small secondary" :disabled="msg.savingCapture" @click="savePhotoQuestion(msg)">
                {{ msg.savingCapture ? '正在收录…' : '加入错题本' }}
              </button>
            </div>
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
        </template>
      </div>
    </div>

    <!-- 输入区（v0.3.0：文本聊天接学习助手 Agent + 拍照批改并存；
         v0.8.1 恢复 v0.6.2 悬浮毛玻璃卡：悬浮在消息区底部，消息从卡下滚过） -->
    <div class="chat-composer" :class="{ 'chat-composer-welcome': isWelcomeScreen }">
      <div class="chat-inner">
        <div class="composer-panel">
          <textarea
            v-model="chatInput"
            class="chat-text-input"
            :class="{ 'chat-text-input-welcome': isWelcomeScreen }"
            rows="1"
            :placeholder="isWelcomeScreen ? '有什么想问的，或说说你正在学习的内容…' : '输入你的问题，回车发送'"
            :disabled="chatSending"
            @keydown.enter.exact.prevent="sendChat()"
          ></textarea>
          <div class="composer-bottom-row">
            <input ref="fileRef" type="file" accept="image/jpeg,image/png,image/webp" hidden @change="onFileChange" />
            <div class="composer-tools">
              <button class="composer-photo-btn" type="button" aria-label="拍照批改" title="拍照批改" :disabled="busy" @click="fileRef?.click()">
                <AppIcon name="camera" :size="18" />
              </button>
              <span v-if="selectedQuestion" class="composer-context"><AppIcon name="clipboard" :size="13" /> {{ selectedQuestion.stem }}</span>
            </div>
            <button class="btn send-btn" type="button" aria-label="发送" title="发送" :disabled="chatSending || !chatInput.trim()" @click="sendChat()">
              <AppIcon name="send" :size="17" />
            </button>
          </div>
        </div>
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
  captureId: number | null
  saved: boolean
  savingCapture: boolean
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
    captureId: null,
    saved: false,
    savingCapture: false,
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
const welcomeBriefing = computed(() => messages.value.find((msg) => msg.kind === 'briefing')?.briefing ?? null)
const isWelcomeScreen = computed(
  () => !loadingInit.value && !messages.value.some((msg) => msg.side === 'user' || (msg.kind !== 'briefing' && msg.text.trim()))
)
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

// ---------- 会话（v0.6.2 状态层；v0.8.1 合并修复）：会话列表与当前会话归 store，
// 与左侧栏会话区共用同一份状态；本页不再自持会话状态，侧栏操作改 store.sessionView，
// 本页 watch 其 seq 变化后同步重渲染（同步逻辑在下方「会话查看同步」段） ----------

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
      result: null,
      captureId: null,
      saved: false,
      savingCapture: false
    })
  } catch (e) {
    console.error(e)
  }
}

// ---------- 会话查看同步（v0.8.1，与 TeacherChat 同一套）：侧栏新建/点选/删除当前会话
// → store.sessionView.seq 递增 → 本页重渲染。学生端与教师端的差异只有一点：
// 简报卡始终保留置顶，会话消息接在简报下方（与原 switchSession 行为一致）。
// fresh=true 表示刚新建的空会话；id=null 表示会话已删光；两者都回到「只剩简报卡」的欢迎态。
let appliedViewSeq = 0
watch(
  () => student.sessionView.seq,
  async (seqVal) => {
    if (seqVal === appliedViewSeq) return
    appliedViewSeq = seqVal
    const view = student.sessionView
    suggestions.value = []
    messages.value = messages.value.filter((m) => m.kind === 'briefing')
    if (!messages.value.length) await prependBriefing()
    if (!view.fresh && view.id != null) {
      try {
        const rows = await student.fetchSessionMessages(view.id)
        rows.forEach((h) =>
          pushMsg({ side: h.role === 'user' ? 'user' : 'ai', kind: 'text', text: h.content })
        )
      } catch (e) {
        pushMsg({ side: 'ai', kind: 'error', text: '打开这条对话失败：' + (errDetail(e) || '请稍后重试。') })
        console.error(e)
      }
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
    const pendingCapture = [...messages.value].reverse().find((item) => item.captureId && !item.saved)
    if (pendingCapture && /加入|收录|保存|放(?:到|进|入)?|加(?:到|进|入)|记(?:到|进)|收藏/.test(text) && /错题本|错题/.test(text)) {
      await student.savePhotoCapture(pendingCapture.captureId!, pendingCapture.text)
      pendingCapture.saved = true
      wait.text = '已经把刚才的题目加入错题本了。'
      await student.loadSessions(true)
      return
    }
    const res = await student.agentChat(text, student.activeSessionId)
    wait.text = res.reply
    if (res.session_id) student.setActiveSession(res.session_id)
    suggestions.value = res.suggestions ?? []
    // 刷新侧栏会话列表（v0.6.2 联动）：首问生成标题、顺序按最近更新重排
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
  const prompt = chatInput.value.trim()
  chatInput.value = ''
  suggestions.value = []
  pushMsg({ side: 'user', kind: 'image', url: URL.createObjectURL(file) })
  if (prompt) pushMsg({ side: 'user', kind: 'text', text: prompt })
  const wait = pushMsg({ side: 'ai', kind: 'text', text: '正在识别题目和作答情况…', pending: true })
  chatSending.value = true
  try {
    // 只有从具体作业题目跳转过来时才自动关联题目，避免把自由上传的照片误绑到默认第一题。
    const explicitQuestionId = selectedQuestion.value?.id ?? null
    const res = await student.reviewPhoto(file, explicitQuestionId)
    wait.pending = false
    wait.questionText = res.question_text
    wait.steps = [...res.steps]
    if (res.mode === 'answer') {
      wait.captureId = res.capture_id
      const agentPrompt = [
        '学生上传的是只有题目、没有学生作答的图片。请先回答题目并讲清思路，不要判断学生做错，也不要创建错题记录。',
        `识别出的题目：${res.question_text.slice(0, 1300)}`,
        prompt ? `学生补充的问题：${prompt.slice(0, 300)}` : ''
      ].filter(Boolean).join('\n')
      const answer = await student.agentChat(agentPrompt, student.activeSessionId)
      wait.text = answer.reply
      if (answer.session_id) student.setActiveSession(answer.session_id)
      suggestions.value = answer.suggestions ?? []
      student.loadSessions(true)
    } else if (res.mode === 'diagnosis' && res.diagnosis) {
      wait.text = res.diagnosis.errors.length
        ? '识别到作答过程并完成批改，发现的错题已自动加入错题本。'
        : '识别到作答过程并完成批改，这道题目前没有发现错误。'
      pushMsg({ side: 'ai', kind: 'diagnosis', result: res.diagnosis })
    } else {
      wait.kind = 'transcribe'
      wait.text = ''
      wait.questionId = explicitQuestionId
    }
  } catch (err) {
    if (wait.captureId) {
      wait.kind = 'text'
      wait.text = `题目已经识别为「${wait.questionText}」，但暂时无法生成讲解。你可以稍后追问，或先把题目加入错题本。`
    } else {
      wait.kind = 'error'
      wait.text = '识别失败：' + (errDetail(err) || '请稍后重试。')
    }
    wait.pending = false
    console.error(err)
  } finally {
    chatSending.value = false
  }
  scrollToBottom()
}

async function savePhotoQuestion(msg: ChatMsg) {
  if (!msg.captureId || msg.saved || msg.savingCapture) return
  msg.savingCapture = true
  try {
    await student.savePhotoCapture(msg.captureId, msg.text)
    msg.saved = true
  } catch (err) {
    pushMsg({ side: 'ai', kind: 'error', text: '加入错题本失败：' + (errDetail(err) || '请稍后重试。') })
  } finally {
    msg.savingCapture = false
    scrollToBottom()
  }
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
      result: null,
      captureId: null,
      saved: false,
      savingCapture: false
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
  // 当前会话定位（v0.6.2）：会话状态归 store 与侧栏共用，loadSessions 首次会自动定位
  // 当前会话（最近更新的一条，与上面 fetchAgentHistory 返回当前会话的口径一致）；
  // appliedViewSeq 对齐当前值，避免把挂载前侧栏的查看请求误当成新切换
  await student.loadSessions()
  appliedViewSeq = student.sessionView.seq
  loadingInit.value = false
  scrollToBottom()
})
</script>

<style scoped>
.chat-layout { position: relative; display: flex; width: calc(100% - 20px); min-width: 0; min-height: 0; flex-direction: column; height: calc(100dvh - 20px); margin: 10px; overflow: hidden; border: 1px solid var(--border); border-radius: 16px; background: var(--card); box-shadow: 0 2px 8px rgba(31, 49, 77, 0.035); }
.chat-inner { max-width: 1280px; width: 100%; margin: 0 auto; padding: 0 20px; }
.chat-header { flex: 0 0 auto; background: var(--card); border-bottom: 0; padding: 9px 0; }
.chat-title { display: flex; align-items: center; gap: 10px; color: var(--text); }
.chat-title-mark { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 11px; background: var(--primary-50); color: var(--primary); }
.chat-title-copy { display: flex; flex-direction: column; gap: 1px; }
.chat-title-copy strong { font-size: 14px; font-weight: 700; line-height: 1.25; }
.chat-title-copy small { color: var(--text-3); font-size: 11px; font-weight: 400; }
.chat-status { margin-left: auto; display: inline-flex; align-items: center; gap: 7px; color: var(--text-3); font-size: 12px; font-weight: 500; }
.chat-status i { width: 7px; height: 7px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 3px var(--green-bg); }
.photo-capture-action { margin-top: 10px; }
.photo-capture-action > span { color: var(--green); font-size: 12px; font-weight: 600; }

.chat-content-shell { display: flex; min-height: 0; flex: 1 1 auto; flex-direction: column; }
.chat-content-shell.welcome-mode { justify-content: center; gap: 18px; overflow-y: auto; padding: 28px 24px 168px; }
/* 底部留白给悬浮输入卡让位（v0.8.1）：最后的消息不被卡片遮住 */
.chat-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 20px 0 168px; background: var(--card); }
.chat-body-welcome { flex: 0 0 auto; overflow: visible; padding: 0; }
.welcome-mode .chat-inner { max-width: 780px; padding: 0; }
.welcome-home { padding: 0 2px; }
.welcome-kicker { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; color: var(--text-2); font-size: 12px; font-weight: 600; }
.welcome-kicker::before { width: 18px; height: 2px; border-radius: 2px; background: var(--primary); content: ''; }
.welcome-home h1 { color: var(--text); font-size: clamp(29px, 2.8vw, 37px); font-weight: 650; line-height: 1.3; letter-spacing: -0.025em; }
.welcome-description { margin-top: 8px; color: var(--text-2); font-size: 14px; }
.welcome-briefing { margin-top: 22px; padding: 16px 18px; border: 1px solid var(--border); border-radius: 14px; background: rgba(255, 255, 255, 0.88); }
.welcome-briefing-heading { display: flex; align-items: center; gap: 9px; color: var(--text); }
.welcome-briefing-heading > div { display: flex; flex-direction: column; gap: 1px; }
.welcome-briefing-heading strong { font-size: 13px; font-weight: 650; }
.welcome-briefing-heading small { color: var(--text-3); font-size: 11px; }
.welcome-briefing-icon { display: grid; width: 28px; height: 28px; place-items: center; border-radius: 9px; background: var(--primary-50); color: var(--text-2); }
.welcome-briefing-stats { display: flex; align-items: baseline; gap: 24px; margin: 13px 0 0 37px; }
.welcome-briefing-stats > div { display: flex; align-items: baseline; gap: 7px; }
.welcome-briefing-stats b { color: var(--text); font-size: 18px; font-weight: 650; }
.welcome-briefing-stats span { color: var(--text-2); font-size: 12px; }
.welcome-briefing-stats a { display: inline-flex; align-items: center; gap: 2px; margin-left: auto; color: var(--primary); font-size: 12px; font-weight: 550; }
.welcome-briefing-stats a :deep(svg) { flex: 0 0 auto; }
.welcome-briefing-assignments { margin: 10px 0 0 37px; border-top: 1px solid var(--border); }
.welcome-briefing-assignment { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 0 0; }
.welcome-briefing-assignment > span { display: flex; min-width: 0; flex-direction: column; }
.welcome-briefing-assignment strong { overflow: hidden; color: var(--text); font-size: 12px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.welcome-briefing-assignment small { color: var(--text-3); font-size: 11px; }
.welcome-briefing-assignment button { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 2px; border: 0; background: transparent; color: var(--primary); font: inherit; font-size: 11.5px; font-weight: 600; cursor: pointer; }
.welcome-briefing-weak { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 11px 0 0 37px; }
.welcome-briefing-weak > span:first-child { margin-right: 2px; color: var(--text-3); font-size: 11px; }
.welcome-briefing-weak > span:not(:first-child) { border-radius: 999px; background: var(--gray-bg); padding: 4px 8px; color: var(--text-2); font-size: 10.5px; }
.welcome-briefing-feedback { margin: 11px 0 0 37px; border-top: 1px solid var(--border); padding-top: 9px; color: var(--text-2); font-size: 11.5px; }
.welcome-briefing-done { display: flex; align-items: flex-start; gap: 10px; margin-top: 13px; border-radius: 10px; background: var(--green-bg); padding: 12px 13px; }
.welcome-done-mark { display: grid; width: 27px; height: 27px; flex: 0 0 27px; place-items: center; border-radius: 50%; background: var(--green); color: #fff; }
.welcome-briefing-done strong { color: #065F46; font-size: 13px; font-weight: 650; }
.welcome-briefing-done p { margin-top: 3px; color: var(--text-2); font-size: 11.5px; }

/* 建议气泡（v0.6.0）：只挂最新一轮回复，淡入上浮 stagger */
.suggest-row { display: flex; gap: 8px; flex-wrap: wrap; margin: -4px 0 16px 40px; }
.suggest-chip {
  border: 1px solid var(--blue-bg);
  background: linear-gradient(135deg, #FFFFFF 0%, var(--primary-50) 100%);
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
.msg-row { display: flex; gap: 10px; margin-bottom: 16px; align-items: flex-start; }
.msg-row.user { flex-direction: row-reverse; }
.msg-avatar {
  width: 30px; height: 30px; border-radius: 50%;
  background: var(--primary-50); color: var(--primary);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 2px;
}
.bubble { border-radius: 14px; padding: 11px 16px; font-size: 14.5px; max-width: 78%; white-space: pre-wrap; word-break: break-word; }
.ai-bubble { background: var(--card); border: 1px solid var(--border); box-shadow: var(--shadow); display: inline-flex; align-items: center; gap: 8px; }
.error-bubble { background: var(--red-bg); color: #991B1B; display: inline-flex; align-items: center; gap: 8px; }
.user-bubble { background: var(--primary); color: #fff; }
.user-image img { max-width: 320px; max-height: 380px; border-radius: 12px; border: 1px solid var(--border); display: block; }

.ai-card {
  background: var(--card); border: 1px solid var(--border); border-radius: 14px;
  box-shadow: var(--shadow); padding: 16px 18px; width: min(900px, 100%);
}
.ai-card-title { font-size: 15px; font-weight: 700; display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }

/* 简报卡片区（v0.2.1 卡片化；v0.4.0 放宽卡宽，统计卡真正横向并排） */
.briefing-card { width: min(1040px, 100%); }
.brief-hello { font-size: 14.5px; margin-bottom: 12px; }
.brief-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.brief-stat-card { border-radius: 12px; padding: 14px 16px; border: 1px solid var(--border); }
.brief-assign { background: var(--primary-50); }
.brief-corr { background: var(--amber-bg); }
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
.brief-recent { margin-top: 14px; font-size: 13px; color: var(--text-2); border-top: 1px solid var(--border); padding-top: 10px; }
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
  border: 1px solid var(--border); border-left: 4px solid var(--border);
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
.error-item { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); }
.encourage { margin-top: 8px; font-size: 14px; }
.detail { margin-top: 6px; font-size: 14px; color: var(--text-2); }
.ok-line { margin-top: 10px; font-size: 14.5px; color: #065F46; display: flex; align-items: center; gap: 6px; }
.followup-box {
  display: flex; gap: 9px; align-items: flex-start;
  background: var(--primary-50); border: 1px solid var(--blue-bg); border-radius: 10px;
  padding: 11px 14px; margin-top: 14px; font-size: 14px;
}
.followup-icon {
  width: 26px; height: 26px; border-radius: 50%; flex-shrink: 0;
  background: var(--primary); color: #fff;
  display: flex; align-items: center; justify-content: center;
}
.followup-box p { padding-top: 3px; }

/* 悬浮输入卡（v0.6.2 版式，v0.8.1 恢复）：毛玻璃卡悬浮在内容区底部，滚动内容从卡下透过去；
   输入框无边框融入卡内，拍照=白底描边圆钮、发送=主色实心圆钮，聚焦时整卡带主色光晕 */
.chat-composer { position: absolute; left: 0; right: 0; bottom: 0; z-index: 6; background: transparent; padding: 10px 0 14px; }
.chat-composer-welcome { background: transparent; }
.composer-panel {
  border: 1px solid var(--border); border-radius: 20px;
  background: rgba(255, 255, 255, 0.88);
  -webkit-backdrop-filter: blur(14px) saturate(1.4);
  backdrop-filter: blur(14px) saturate(1.4);
  padding: 13px 15px 11px;
  box-shadow: 0 14px 36px rgba(15, 23, 42, 0.13), 0 2px 8px rgba(15, 23, 42, 0.06);
  transition: border-color 0.18s ease, box-shadow 0.25s ease;
}
.composer-panel:focus-within {
  border-color: rgba(29, 78, 216, 0.35);
  box-shadow: 0 14px 36px rgba(15, 23, 42, 0.13), 0 2px 8px rgba(15, 23, 42, 0.06), 0 0 0 3px rgba(29, 78, 216, 0.14);
}
.chat-text-input { display: block; width: 100%; min-width: 0; min-height: 40px; max-height: 150px; resize: none; padding: 7px 8px; border: 0; border-radius: 10px; outline: 0; box-shadow: none; font: inherit; font-size: 15px; line-height: 1.65; }
.chat-text-input:focus { border: 0; outline: 0; box-shadow: none; }
.chat-text-input-welcome { min-height: 54px; font-size: 16px; }
.composer-bottom-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 7px; }
.composer-tools { display: flex; min-width: 0; align-items: center; gap: 9px; }
.composer-photo-btn { display: inline-flex; width: 42px; height: 42px; align-items: center; justify-content: center; border: 1px solid var(--border); border-radius: 50%; background: #fff; color: var(--text-2); padding: 0; cursor: pointer; transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease, transform 0.2s ease; }
.composer-photo-btn:hover:not(:disabled) { border-color: rgba(29, 78, 216, 0.35); background: var(--primary-50); color: var(--primary); }
.composer-photo-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.composer-context { display: inline-flex; min-width: 0; align-items: center; gap: 5px; overflow: hidden; color: var(--text-3); font-size: 11.5px; white-space: nowrap; text-overflow: ellipsis; }
.send-btn { display: inline-flex; width: 42px; height: 42px; align-items: center; justify-content: center; padding: 0; border-radius: 50%; flex-shrink: 0; transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease; }
.send-btn:hover:not(:disabled) { transform: scale(1.07); }
.send-btn:disabled { background: var(--gray-bg); color: var(--text-3); cursor: default; }
.send-btn:not(:disabled) { box-shadow: 0 3px 9px rgba(29, 78, 216, 0.2); }
.chat-composer-welcome .chat-inner { max-width: 780px; padding: 0; }
.spin { animation: chat-spin 1s linear infinite; }
@keyframes chat-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .suggest-chip { animation: none; transition: none; }
  .composer-panel, .send-btn, .composer-photo-btn { transition: none; }
  .send-btn:hover:not(:disabled) { transform: none; }
}

@media (max-width: 960px) {
  .chat-layout { height: calc(100dvh - 72px); }
  .chat-status { display: none; }
  .user-image img { max-width: 240px; }
  .bubble { max-width: 88%; }
  .chat-content-shell.welcome-mode { gap: 16px; padding: 20px 18px 150px; }
  .chat-composer-welcome .chat-inner { padding: 0; }
  .composer-panel { padding: 10px 11px; }
}

@media (max-width: 620px) {
  .chat-header { padding: 7px 0; }
  .chat-inner { padding-right: 14px; padding-left: 14px; }
  .chat-title-mark { width: 31px; height: 31px; }
  .chat-title-copy small { font-size: 10px; }
  .welcome-kicker { margin-bottom: 10px; }
  .welcome-home h1 { font-size: clamp(27px, 7.5vw, 34px); }
  .welcome-description { max-width: 330px; font-size: 13px; }
  .welcome-briefing { margin-top: 17px; padding: 12px; }
  .welcome-briefing-stats { flex-wrap: wrap; gap: 12px; margin-left: 0; }
  .welcome-briefing-stats > div { flex-direction: column; gap: 0; }
  .welcome-briefing-stats a { margin-left: auto; font-size: 11px; }
  .welcome-briefing-assignments, .welcome-briefing-weak, .welcome-briefing-feedback { margin-left: 0; }
  .composer-bottom-row { gap: 6px; }
  .composer-tools { gap: 5px; }
  .composer-context { max-width: 38vw; }
}
</style>
