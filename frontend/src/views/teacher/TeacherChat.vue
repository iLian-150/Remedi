<!-- 教师端：AI 助手（v0.5.0 新增；v0.6.0 全屏版式 + 会话制 + 建议气泡）
     班级数据助理：可问某份作业提交情况、知识点错误率、班级知识修复率、学生画像等，
     回答全部来自系统真实数据（LangGraph 教师 Agent，接口 4.12~4.22）。
     v0.6.0：版式改全屏（内容铺满、对话列居中放宽至约 960px、输入区固定底部整宽）；
     对话按会话组织——「新对话」新建会话，旧会话经页头「历史对话」面板找回/删除；
     每轮回复后在最新回复下方弹出建议气泡（后端 suggestions 字段，点击直接发送）。 -->
<template>
  <div class="tchat-shell">
    <div class="tchat-col">
      <div class="tchat-head">
        <div>
          <h2>AI 助手</h2>
          <p class="tchat-sub">问问班级的情况：谁还没交作业、哪个知识点最严重、修复率怎么样。</p>
        </div>
        <div class="tchat-head-actions">
          <div class="session-anchor">
            <button class="btn secondary inline-icon" @click="togglePanel">
              <AppIcon name="history" :size="15" /> 历史对话
            </button>
            <SessionPanel
              v-if="panelOpen"
              :sessions="sessions"
              :current-id="currentSessionId"
              :loading="sessionsLoading"
              @close="panelOpen = false"
              @create="startNewSession"
              @select="switchSession"
              @remove="removeSession"
            />
          </div>
          <button class="btn secondary inline-icon" :disabled="resetting" @click="startNewSession">
            <AppIcon name="plus" :size="15" /> 新对话
          </button>
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

        <div class="tchat-composer">
          <input
            v-model="input"
            class="tchat-input"
            type="text"
            placeholder="输入问题，回车发送（例如：《第一周数学作业》谁还没交？）"
            :disabled="sending"
            @keyup.enter="sendText(input)"
          />
          <button class="btn inline-icon" :disabled="sending || !input.trim()" @click="sendText(input)">
            <AppIcon name="send" :size="16" /> 发送
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useTeacherStore } from '../../stores/teacher'
import type { ChatSession } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'
import SessionPanel from '../../components/SessionPanel.vue'

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
const resetting = ref(false)
const loadingInit = ref(true)
const toast = ref('')
const error = ref('')
const bodyRef = ref<HTMLElement | null>(null)

// ---------- 会话（v0.6.0） ----------
const sessions = ref<ChatSession[]>([])
const currentSessionId = ref<number | null>(null)
const panelOpen = ref(false)
const sessionsLoading = ref(false)

// ---------- 建议气泡（v0.6.0）：只存最新一轮的建议 ----------
const suggestions = ref<string[]>([])

const WELCOME = () =>
  `${auth.name}，你好！我是你的班级数据助理。\n` +
  '你可以直接问我：某份作业谁还没交、哪个知识点错误率最高、班级知识修复率，或者某个学生最近的情况。点上方任意一个快捷问题也能直接问。'

function pushMsg(side: 'ai' | 'user', text: string, pending = false): Msg {
  const m: Msg = { id: ++seq, side, text, pending }
  messages.value.push(m)
  scrollToBottom()
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
  return typeof d === 'string' ? d : ''
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
  sending.value = true
  try {
    const res = await teacher.agentChat(text, currentSessionId.value)
    wait.text = res.reply
    if (res.session_id) currentSessionId.value = res.session_id
    suggestions.value = res.suggestions ?? []
  } catch (e) {
    wait.text = '查询失败：' + (errDetail(e) || '请稍后重试。')
    console.error(e)
  } finally {
    wait.pending = false
    sending.value = false
    scrollToBottom()
  }
}

// ---------- 会话操作（v0.6.0） ----------
async function loadSessions() {
  sessionsLoading.value = true
  try {
    sessions.value = await teacher.fetchSessions()
  } catch (e) {
    console.error(e)
  } finally {
    sessionsLoading.value = false
  }
}

function togglePanel() {
  panelOpen.value = !panelOpen.value
  if (panelOpen.value) loadSessions()
}

function renderHistory(rows: { role: string; content: string }[]) {
  messages.value = []
  if (rows.length) {
    rows.forEach((h) => pushMsg(h.role === 'user' ? 'user' : 'ai', h.content))
  } else {
    pushMsg('ai', WELCOME())
  }
}

async function startNewSession() {
  if (resetting.value) return
  resetting.value = true
  try {
    const s = await teacher.newAgentSession()
    currentSessionId.value = s.id
    suggestions.value = []
    panelOpen.value = false
    renderHistory([])
    showToast('已开始新对话')
  } catch (e) {
    error.value = '开启新对话失败：' + (errDetail(e) || '请稍后重试。')
    console.error(e)
  } finally {
    resetting.value = false
  }
}

async function switchSession(s: ChatSession) {
  if (s.id === currentSessionId.value) {
    panelOpen.value = false
    return
  }
  try {
    const rows = await teacher.fetchSessionMessages(s.id)
    currentSessionId.value = s.id
    suggestions.value = []
    panelOpen.value = false
    renderHistory(rows)
    scrollToBottom()
  } catch (e) {
    error.value = '打开这条对话失败：' + (errDetail(e) || '请稍后重试。')
    console.error(e)
  }
}

async function removeSession(s: ChatSession) {
  try {
    await teacher.deleteSession(s.id)
    sessions.value = sessions.value.filter((x) => x.id !== s.id)
    if (s.id === currentSessionId.value) {
      // 删掉的是当前会话：切到列表里最新的一条，没有就回到欢迎态
      const next = sessions.value[0]
      if (next) {
        const rows = await teacher.fetchSessionMessages(next.id)
        currentSessionId.value = next.id
        renderHistory(rows)
      } else {
        currentSessionId.value = null
        renderHistory([])
      }
      suggestions.value = []
    }
    showToast('已删除这条对话')
  } catch (e) {
    error.value = '删除失败：' + (errDetail(e) || '请稍后重试。')
    console.error(e)
  }
}

onMounted(async () => {
  try {
    const history = await teacher.fetchAgentHistory()
    renderHistory(history)
    // 当前会话 = 列表里最近更新的一条
    await loadSessions()
    currentSessionId.value = sessions.value[0]?.id ?? null
  } catch (e) {
    renderHistory([])
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
.tchat-head-actions { display: flex; gap: 8px; align-items: flex-start; }
.session-anchor { position: relative; }

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
  flex: 1; min-height: 380px; overflow: hidden;
}
.tchat-body { flex: 1; overflow-y: auto; padding: 18px 20px; }
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

.tchat-composer {
  border-top: 1px solid var(--border); padding: 12px 14px;
  display: flex; gap: 10px; align-items: center;
}
.tchat-input { flex: 1; min-width: 0; padding: 12px 14px; font-size: 14.5px; }
.spin { animation: tchat-spin 1s linear infinite; flex-shrink: 0; margin-top: 2px; }
@keyframes tchat-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .chip, .suggest-chip { transition: none; }
  .suggest-chip { animation: none; }
  .spin { animation: none; }
}
@media (max-width: 960px) {
  .tchat-shell { height: calc(100dvh - 52px); padding: 14px 14px 16px; }
  .bubble { max-width: 88%; }
  .suggest-row { margin-left: 0; }
}
</style>
