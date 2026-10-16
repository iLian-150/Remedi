<!-- 教师端：AI 助手（v0.5.0 新增；v0.6.0 全屏版式 + 会话制 + 建议气泡）
     班级数据助理：可问某份作业提交情况、知识点错误率、班级知识修复率、学生画像等，
     回答全部来自系统真实数据（LangGraph 教师 Agent，接口 4.12~4.22）。
     v0.6.0：版式改全屏（内容铺满、对话列居中放宽至约 960px、输入区固定底部整宽）；
     对话按会话组织；每轮回复后在最新回复下方弹出建议气泡（后端 suggestions 字段，点击直接发送）。
     v0.6.2：会话导航移入左侧栏（ChatGPT 式），本页只管消息流；输入区改悬浮毛玻璃卡。 -->
<template>
  <div class="tchat-shell">
    <div class="tchat-col">
      <div class="tchat-head">
        <div>
          <h2>AI 助手</h2>
          <p class="tchat-sub">问问班级的情况：谁还没交作业、哪个知识点最严重、修复率怎么样。</p>
        </div>
      </div>

      <div v-if="toast" class="ok-msg">{{ toast }}</div>
      <div v-if="error" class="error-msg">{{ error }}</div>

      <!-- 快捷提问：点一下直接发送 -->
      <div class="chip-row">
        <button
          v-for="chip in CHIPS"
          :key="chip"
          class="chip"
          :disabled="sending"
          @click="sendText(chip)"
        >
          <AppIcon name="sparkles" :size="13" /> {{ chip }}
        </button>
      </div>

      <div class="tchat-panel">
        <div class="tchat-body" ref="bodyRef">
          <div v-if="historyHasMore || historyLoadingOlder || historyLoadError" class="history-pager">
            <button
              v-if="historyHasMore"
              type="button"
              class="history-pager-button"
              :disabled="historyLoadingOlder || sending"
              @click="loadOlderHistory"
            >
              {{ historyLoadingOlder ? '正在加载…' : '加载更早消息' }}
            </button>
            <span v-if="historyLoadError" class="history-pager-error">{{ historyLoadError }}</span>
          </div>
          <div v-for="msg in messages" :key="msg.id" class="msg-row" :class="msg.side">
            <div v-if="msg.side === 'ai'" class="msg-avatar"><AppIcon name="sparkles" :size="16" /></div>
            <div class="bubble" :class="msg.side === 'ai' ? 'ai-bubble' : 'user-bubble'">
              <AppIcon v-if="msg.pending" name="spinner" :size="15" class="spin" />
              {{ msg.text }}
            </div>
          </div>

          <!-- 建议气泡（v0.6.0）：只挂最新一轮回复，stagger 淡入上浮，点击直接发送 -->
          <div v-if="suggestions.length && !sending" class="suggest-row">
            <button
              v-for="(s, i) in suggestions"
              :key="s"
              class="suggest-chip"
              :style="{ animationDelay: `${i * 70}ms` }"
              @click="sendText(s)"
            >
              {{ s }}
            </button>
          </div>

          <div v-if="loadingInit" class="loading">正在加载对话…</div>
        </div>

        <!-- 输入区（v0.6.2 改悬浮卡：毛玻璃卡悬浮在面板底部，消息从卡下滚过；
             输入框无边框融入卡内，发送是卡内右侧主色圆形钮） -->
        <div class="tchat-composer">
          <input
            v-model="input"
            class="tchat-input"
            type="text"
            placeholder="输入问题，回车发送（例如：《第一周数学作业》谁还没交？）"
            :disabled="sending"
            @keyup.enter="sendText(input)"
          />
          <button
            class="send-circle"
            title="发送"
            :disabled="sending || !input.trim()"
            @click="sendText(input)"
          >
            <AppIcon name="send" :size="17" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useTeacherStore } from '../../stores/teacher'
import type { AgentHistoryCursor, AgentHistoryPage, AgentHistoryItem } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'

const auth = useAuthStore()
const teacher = useTeacherStore()

const CHIPS = [
  '今天谁还没交作业',
  '哪个知识点错误率最高',
  '班级知识修复率怎么样',
  '谁的订正还没完成'
]

interface Msg {
  id: number
  side: 'ai' | 'user'
  text: string
  pending: boolean
}

const messages = ref<Msg[]>([])
let seq = 0
const input = ref('')
const sending = ref(false)
const loadingInit = ref(true)
const toast = ref('')
const error = ref('')
const bodyRef = ref<HTMLElement | null>(null)
const historyHasMore = ref(false)
const historyLoadingOlder = ref(false)
const historyLoadError = ref('')
const historyCursor = ref<AgentHistoryCursor | null>(null)
let activeStreamController: AbortController | null = null
let historyRequestToken = 0

function isAbortError(error: unknown): boolean {
  return typeof error === 'object' && error !== null &&
    'name' in error && (error as { name?: unknown }).name === 'AbortError'
}

// ---------- 会话（v0.6.0 会话制；v0.6.2 导航移入左侧栏，会话状态归 store 与侧栏共用） ----------
// 本页不持有会话列表：侧栏操作改 store.sessionView，本页 watch seq 变化后同步重渲染。
// ---------- 建议气泡（v0.6.0）：只存最新一轮的建议 ----------
const suggestions = ref<string[]>([])

const WELCOME = () =>
  `${auth.name}，你好！我是你的班级数据助理。\n` +
  '你可以直接问我：某份作业谁还没交、哪个知识点错误率最高、班级知识修复率，或者某个学生最近的情况。点上方任意一个快捷问题也能直接问。'

function createMsg(side: 'ai' | 'user', text: string, pending = false): Msg {
  return { id: ++seq, side, text, pending }
}

function pushMsg(side: 'ai' | 'user', text: string, pending = false, shouldScroll = true): Msg {
  const m = createMsg(side, text, pending)
  messages.value.push(m)
  if (shouldScroll) scrollToBottom()
  return m
}

function scrollToBottom() {
  nextTick(() => {
    const el = bodyRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function errDetail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  if (typeof d === 'string') return d
  return e instanceof Error ? e.message : ''
}

function showToast(text: string) {
  toast.value = text
  setTimeout(() => {
    if (toast.value === text) toast.value = ''
  }, 2600)
}

async function sendText(raw: string) {
  const text = raw.trim()
  if (!text || sending.value) return
  if (text.length > 2000) {
    error.value = '这条消息有点太长了（最多 2000 字），拆成两条发吧。'
    return
  }
  error.value = ''
  input.value = ''
  suggestions.value = []
  pushMsg('user', text)
  const wait = pushMsg('ai', '正在查询…', true)
  const controller = new AbortController()
  activeStreamController = controller
  sending.value = true
  try {
    wait.text = ''
    let receivedCharacter = false
    const res = await teacher.agentChatStream(text, teacher.activeSessionId, (character) => {
      if (!receivedCharacter) {
        wait.text = ''
        wait.pending = false
        receivedCharacter = true
      }
      wait.text += character
      scrollToBottom()
    }, controller.signal)
    if (res.session_id) teacher.setActiveSession(res.session_id)
    suggestions.value = res.suggestions ?? []
    // 刷新侧栏会话列表（v0.6.2）：首问会生成标题，顺序也按最近更新重排
    teacher.loadSessions(true)
  } catch (e) {
    if (isAbortError(e)) return
    wait.text = '查询失败：' + (errDetail(e) || '请稍后重试。')
    console.error(e)
  } finally {
    if (activeStreamController === controller) activeStreamController = null
    wait.pending = false
    sending.value = false
    scrollToBottom()
  }
}

onUnmounted(() => activeStreamController?.abort())

function restoreHistoryMessage(row: AgentHistoryItem, shouldScroll = false) {
  pushMsg(row.role === 'user' ? 'user' : 'ai', row.content, false, shouldScroll)
}

function updateHistoryPage(page: AgentHistoryPage | null) {
  const beforeCreatedAt = page?.before_created_at
  const beforeId = page?.before_id
  historyHasMore.value = Boolean(page?.has_more && beforeCreatedAt && beforeId != null)
  historyCursor.value = historyHasMore.value && beforeCreatedAt && beforeId != null
    ? { before_created_at: beforeCreatedAt, before_id: beforeId }
    : null
  historyLoadError.value = ''
}

function renderHistory(page: AgentHistoryPage | null) {
  messages.value = []
  updateHistoryPage(page)
  if (page?.items.length) {
    page.items.forEach((item) => restoreHistoryMessage(item))
  } else {
    pushMsg('ai', WELCOME(), false, false)
  }
}

async function loadOlderHistory() {
  const sessionId = teacher.sessionView.id ?? teacher.activeSessionId
  const cursor = historyCursor.value
  if (sessionId == null || !cursor || historyLoadingOlder.value) return
  const requestToken = ++historyRequestToken
  historyLoadingOlder.value = true
  historyLoadError.value = ''
  try {
    const page = await teacher.fetchSessionMessages(sessionId, cursor)
    const currentSessionId = teacher.sessionView.id ?? teacher.activeSessionId
    if (requestToken !== historyRequestToken || currentSessionId !== sessionId) return
    const body = bodyRef.value
    const previousHeight = body?.scrollHeight ?? 0
    const previousTop = body?.scrollTop ?? 0
    const olderMessages = page.items.map((item) => createMsg(
      item.role === 'user' ? 'user' : 'ai', item.content
    ))
    messages.value.unshift(...olderMessages)
    updateHistoryPage(page)
    await nextTick()
    if (body) body.scrollTop = previousTop + body.scrollHeight - previousHeight
  } catch (e) {
    if (requestToken === historyRequestToken) {
      historyLoadError.value = '加载更早消息失败，请重试。'
      console.error(e)
    }
  } finally {
    if (requestToken === historyRequestToken) historyLoadingOlder.value = false
  }
}

// ---------- 会话查看同步（v0.6.2）：侧栏操作 → store.sessionView.seq 递增 → 本页重渲染 ----------
let appliedViewSeq = 0
watch(
  () => teacher.sessionView.seq,
  async (seq) => {
    if (seq === appliedViewSeq) return
    appliedViewSeq = seq
    const requestToken = ++historyRequestToken
    const view = teacher.sessionView
    const viewId = view.id
    suggestions.value = []
    error.value = ''
    historyHasMore.value = false
    historyCursor.value = null
    historyLoadError.value = ''
    historyLoadingOlder.value = false
    messages.value = []
    if (view.fresh) {
      renderHistory(null)
      showToast('已开始新对话')
    } else if (viewId != null) {
      try {
        const page = await teacher.fetchSessionMessages(viewId)
        if (requestToken !== historyRequestToken) return
        renderHistory(page)
      } catch (e) {
        if (requestToken !== historyRequestToken) return
        error.value = '打开这条对话失败：' + (errDetail(e) || '请稍后重试。')
        console.error(e)
      }
    } else {
      // 会话全删光了：回到欢迎态
      renderHistory(null)
    }
    scrollToBottom()
  }
)

onMounted(async () => {
  let initialViewSeq: number | null = null
  let initialSessionId: number | null = null
  try {
    await teacher.loadSessions()
    // 先复用侧栏的会话列表请求，避免 /agent/history 与 /agent/sessions
    // 并发触发首次旧消息迁移；正文也读取侧栏当前激活会话的完整消息。
    initialViewSeq = teacher.sessionView.seq
    initialSessionId = teacher.activeSessionId
    appliedViewSeq = initialViewSeq
    const history = initialSessionId == null
      ? null
      : await teacher.fetchSessionMessages(initialSessionId)
    // 加载期间用户可能已切换会话，不能让较早的响应覆盖新会话内容。
    if (teacher.sessionView.seq === initialViewSeq && teacher.activeSessionId === initialSessionId) {
      renderHistory(history)
    }
  } catch (e) {
    if (initialViewSeq == null || teacher.sessionView.seq === initialViewSeq) {
      renderHistory(null)
    }
    console.error(e)
  } finally {
    loadingInit.value = false
    scrollToBottom()
  }
})
</script>

<style scoped>
/* 全屏版式（v0.6.0）：不再套 .page 的窄列，内容铺满内容区、对话列居中放宽 */
.tchat-shell { flex: 1; display: flex; flex-direction: column; height: 100dvh; padding: 20px 28px 22px; }
.tchat-col { flex: 1; display: flex; flex-direction: column; width: 100%; max-width: 960px; margin: 0 auto; min-height: 0; }
.tchat-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.tchat-head h2 { font-size: 24px; letter-spacing: 0.2px; }
.tchat-sub { font-size: 13.5px; color: var(--text-2); margin-top: 4px; }

.chip-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.chip {
  display: inline-flex; align-items: center; gap: 6px;
  border: 1px solid #D7E3FA;
  background: linear-gradient(135deg, #EFF5FF 0%, #FFFFFF 70%);
  color: var(--primary);
  border-radius: 999px; padding: 7px 14px; font-size: 13.5px; font-weight: 600;
  cursor: pointer; font-family: var(--font);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.chip:hover:not(:disabled) { transform: translateY(-1px); box-shadow: var(--shadow); }
.chip:disabled { opacity: 0.55; cursor: not-allowed; }

.tchat-panel {
  background: var(--card); border: 1px solid #EDF0F4; border-radius: 14px;
  box-shadow: var(--shadow); display: flex; flex-direction: column;
  flex: 1; min-height: 380px; overflow: hidden; position: relative;
}
/* 底部留白给悬浮输入卡让位，最后的消息不被卡片遮住 */
.tchat-body { flex: 1; overflow-y: auto; padding: 18px 20px 118px; }
.history-pager { display: flex; flex-direction: column; align-items: center; gap: 6px; margin: 0 0 16px; }
.history-pager-button { border: 1px solid var(--border); border-radius: 999px; padding: 7px 14px; background: var(--card); color: var(--primary); font: inherit; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.history-pager-button:disabled { opacity: 0.55; cursor: wait; }
.history-pager-error { color: var(--red); font-size: 12px; }
.msg-row { display: flex; gap: 10px; margin-bottom: 14px; align-items: flex-start; }
.msg-row.user { flex-direction: row-reverse; }
.msg-avatar {
  width: 30px; height: 30px; border-radius: 50%;
  background: var(--primary-50); color: var(--primary);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 2px;
}
.bubble { border-radius: 14px; padding: 11px 16px; font-size: 14.5px; max-width: 78%; white-space: pre-wrap; word-break: break-word; }
.ai-bubble { background: #F8FAFF; border: 1px solid #EDF0F4; display: inline-flex; align-items: flex-start; gap: 8px; }
.user-bubble { background: var(--primary); color: #fff; }

/* 建议气泡（v0.6.0）：本轮回复后淡入上浮，stagger 错峰 */
.suggest-row { display: flex; gap: 8px; flex-wrap: wrap; margin: 2px 0 10px 40px; }
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

/* 悬浮输入卡（v0.6.2）：毛玻璃卡悬浮在面板底部，滚动内容从卡下透过去；
   输入框无边框融入卡内，发送是卡内右侧主色圆形钮，聚焦时卡带主色光晕 */
.tchat-composer {
  position: absolute; left: 16px; right: 16px; bottom: 14px; z-index: 5;
  display: flex; gap: 8px; align-items: center;
  background: rgba(255, 255, 255, 0.88);
  -webkit-backdrop-filter: blur(14px) saturate(1.4);
  backdrop-filter: blur(14px) saturate(1.4);
  border: 1px solid #E2E9F5; border-radius: 20px;
  box-shadow: 0 14px 36px rgba(15, 23, 42, 0.13), 0 2px 8px rgba(15, 23, 42, 0.06);
  padding: 10px 12px;
  transition: box-shadow 0.25s ease, border-color 0.25s ease;
}
.tchat-composer:focus-within {
  border-color: #B9CFF7;
  box-shadow: 0 14px 36px rgba(15, 23, 42, 0.13), 0 0 0 3px rgba(29, 78, 216, 0.14);
}
.tchat-input {
  flex: 1; min-width: 0; padding: 10px 6px; font-size: 15px;
  border: none; background: transparent; box-shadow: none;
}
.tchat-input:focus { border: none; box-shadow: none; outline: none; }
.send-circle {
  width: 42px; height: 42px; border-radius: 50%; flex-shrink: 0;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--primary); border: 1px solid var(--primary); color: #fff;
  box-shadow: 0 4px 12px rgba(29, 78, 216, 0.35); cursor: pointer; font-family: var(--font);
  transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
}
.send-circle:hover:not(:disabled) { transform: scale(1.07); box-shadow: 0 6px 16px rgba(29, 78, 216, 0.42); }
.send-circle:disabled { opacity: 0.45; cursor: not-allowed; }
.spin { animation: tchat-spin 1s linear infinite; flex-shrink: 0; margin-top: 2px; }
@keyframes tchat-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .chip, .suggest-chip { transition: none; }
  .suggest-chip { animation: none; }
  .spin { animation: none; }
  .tchat-composer, .send-circle { transition: none; }
  .send-circle:hover:not(:disabled) { transform: none; }
}
@media (max-width: 960px) {
  .tchat-shell { height: calc(100dvh - 52px); padding: 14px 14px 16px; }
  .bubble { max-width: 88%; }
  .suggest-row { margin-left: 0; }
  .tchat-composer { left: 10px; right: 10px; bottom: 10px; border-radius: 18px; }
  .tchat-body { padding-bottom: 112px; }
}
</style>
