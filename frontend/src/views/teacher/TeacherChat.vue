<!-- 教师端：AI 助手（v0.5.0 新增）
     班级数据助理：可问某份作业提交情况、知识点错误率、班级知识修复率、学生画像等，
     回答全部来自系统真实数据（LangGraph 教师 Agent，接口 4.12~4.14）。
     右上角「新对话」清空服务端记录并重置对话区（不进左侧导航，与学生端口径一致）。 -->
<template>
  <div class="page tchat-page">
    <div class="page-head tchat-head">
      <div>
        <h2>AI 助手</h2>
        <p class="page-sub">问问班级的情况：谁还没交作业、哪个知识点最严重、修复率怎么样。</p>
      </div>
      <button class="btn secondary inline-icon" :disabled="resetting" @click="newSession">
        <AppIcon name="plus" :size="15" /> 新对话
      </button>
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
        {{ chip }}
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
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useTeacherStore } from '../../stores/teacher'
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
const resetting = ref(false)
const loadingInit = ref(true)
const toast = ref('')
const error = ref('')
const bodyRef = ref<HTMLElement | null>(null)

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
  pushMsg('user', text)
  const wait = pushMsg('ai', '正在查询…', true)
  sending.value = true
  try {
    wait.text = await teacher.agentChat(text)
  } catch (e) {
    wait.text = '查询失败：' + (errDetail(e) || '请稍后重试。')
    console.error(e)
  } finally {
    wait.pending = false
    sending.value = false
    scrollToBottom()
  }
}

async function newSession() {
  if (resetting.value) return
  resetting.value = true
  try {
    await teacher.newAgentSession()
    messages.value = []
    pushMsg('ai', WELCOME())
    showToast('已开始新对话')
  } catch (e) {
    error.value = '开启新对话失败：' + (errDetail(e) || '请稍后重试。')
    console.error(e)
  } finally {
    resetting.value = false
  }
}

onMounted(async () => {
  try {
    const history = await teacher.fetchAgentHistory()
    if (history.length) {
      history.forEach((h) => pushMsg(h.role === 'user' ? 'user' : 'ai', h.content))
    } else {
      pushMsg('ai', WELCOME())
    }
  } catch (e) {
    pushMsg('ai', WELCOME())
    console.error(e)
  } finally {
    loadingInit.value = false
    scrollToBottom()
  }
})
</script>

<style scoped>
.tchat-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.chip-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.chip {
  border: 1px solid #DBEAFE; background: var(--primary-50); color: var(--primary);
  border-radius: 999px; padding: 7px 14px; font-size: 13.5px; font-weight: 600;
  cursor: pointer; font-family: var(--font);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.chip:hover:not(:disabled) { transform: translateY(-1px); box-shadow: var(--shadow); }
.chip:disabled { opacity: 0.55; cursor: not-allowed; }
.tchat-panel {
  background: var(--card); border: 1px solid #EDF0F4; border-radius: 14px;
  box-shadow: var(--shadow); display: flex; flex-direction: column;
  height: calc(100dvh - 268px); min-height: 420px; overflow: hidden;
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
.tchat-composer {
  border-top: 1px solid var(--border); padding: 12px 14px;
  display: flex; gap: 10px; align-items: center;
}
.tchat-input { flex: 1; min-width: 0; padding: 12px 14px; font-size: 14.5px; }
.spin { animation: tchat-spin 1s linear infinite; flex-shrink: 0; margin-top: 2px; }
@keyframes tchat-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .chip { transition: none; }
  .spin { animation: none; }
}
@media (max-width: 960px) {
  .tchat-panel { height: calc(100dvh - 300px); }
  .bubble { max-width: 88%; }
}
</style>
