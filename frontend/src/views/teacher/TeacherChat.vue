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
        <h2>AI 助手</h2>
      </div>

      <div v-if="error" class="error-msg">{{ error }}</div>
      <div v-if="knowledgeImportNotice" class="ok-msg" role="status">
        <AppIcon name="check" :size="15" /> {{ knowledgeImportNotice }}
      </div>

      <div class="tchat-panel">
        <div class="tchat-body" :class="{ 'tchat-body-welcome': isWelcomeState, 'tchat-body-image-composer': selectedFile }" ref="bodyRef">
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
          <div v-for="msg in messages" :key="msg.id" class="msg-row" :class="[msg.side, { 'workflow-event-hidden': msg.workflowEventHidden }]">
            <div v-if="msg.side === 'ai'" class="msg-avatar"><AppIcon name="sparkles" :size="16" /></div>
            <div class="msg-content" :class="{ 'has-workflow': msg.workflowDraft || msg.workflowPublished }">
              <div
                class="bubble"
                :class="[
                  msg.side === 'ai' ? 'ai-bubble' : 'user-bubble',
                  { 'welcome-bubble': isWelcomeState && msg.side === 'ai' }
                ]"
              >
                <div v-if="msg.pending" class="pending-status">
                  <ThinkingStatus />
                  <span class="pending-elapsed">· {{ pendingElapsedSeconds }} 秒</span>
                </div>
                <template v-else>
                  <button
                    v-if="msg.imageUrl"
                    class="message-image"
                    type="button"
                    :aria-label="`放大${msg.imageName || '上传图片'}`"
                    @click="openImagePreview(msg.imageUrl, msg.imageName || '上传图片')"
                  >
                    <img :src="msg.imageUrl" :alt="msg.imageName || '上传图片'" />
                  </button>
                  <span v-else-if="msg.imageName" class="chat-attachment-name">
                    <AppIcon name="file" :size="16" /> {{ msg.imageName }}
                  </span>
                  <div v-if="msg.text">{{ msg.text }}</div>
                </template>
              </div>
              <div v-if="msg.workflowDraft" class="chat-workflow">
                <TeacherPublish
                  :key="msg.id"
                  embedded
                  chat-workflow
                  :initial-draft="msg.workflowDraft"
                  @published="onWorkflowPublished(msg, $event)"
                  @cancel="msg.workflowDraft = undefined"
                />
              </div>
              <div v-else-if="msg.workflowPublished" class="chat-workflow-success">
                <span><AppIcon name="check" :size="16" /> 已发布《{{ msg.workflowPublished }}》</span>
                <router-link to="/teacher/assignments">作业管理 <AppIcon name="arrow-right" :size="14" /></router-link>
              </div>
            </div>
          </div>

          <div v-if="isWelcomeState" class="welcome-prompts">
            <button
              v-for="chip in CHIPS"
              :key="chip"
              :disabled="sending"
              @click="sendText(chip)"
            >
              {{ chip }}
            </button>
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

        <ChatComposer
          v-model="input"
          :selected-file="selectedFile"
          :selected-file-url="selectedFileUrl"
          :sending="sending"
          :upload-disabled="sending"
          :welcome="isWelcomeState"
          @send="sendComposer"
          @file-selected="onComposerFileSelected"
          @clear-file="clearSelectedFile"
          @preview-image="openImagePreview"
        />
      </div>
      <div v-if="imagePreview" class="image-lightbox" role="dialog" aria-modal="true" aria-label="图片预览" @click.self="closeImagePreview">
        <button class="image-lightbox-close" type="button" aria-label="关闭图片预览" title="关闭" @click="closeImagePreview">
          <AppIcon name="x" :size="21" />
        </button>
        <img :src="imagePreview.url" :alt="imagePreview.alt" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useTeacherStore } from '../../stores/teacher'
import type { AgentHistoryCursor, AgentHistoryPage, AgentHistoryItem, SubjectAgentCode, TeacherAssignment, TeacherAssignmentDraftSeed } from '../../api/types'
import ThinkingStatus from '../../components/ThinkingStatus.vue'
import AppIcon from '../../components/icons/AppIcon.vue'
import ChatComposer from '../../components/ChatComposer.vue'

const TeacherPublish = defineAsyncComponent(() => import('./TeacherPublish.vue'))

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
  imageUrl?: string
  imageName?: string
  workflowDraft?: TeacherAssignmentDraftSeed
  workflowPublished?: string
  workflowEventHidden?: boolean
}

const messages = ref<Msg[]>([])
let seq = 0
const input = ref('')
const selectedFile = shallowRef<File | null>(null)
const selectedFileUrl = ref('')
const imagePreview = ref<{ url: string; alt: string } | null>(null)
const imageObjectUrls = new Set<string>()
const sending = ref(false)
const loadingInit = ref(true)
const error = ref('')
const knowledgeImportNotice = ref('')
const bodyRef = ref<HTMLElement | null>(null)
const historyHasMore = ref(false)
const historyLoadingOlder = ref(false)
const historyLoadError = ref('')
const historyCursor = ref<AgentHistoryCursor | null>(null)
let activeStreamController: AbortController | null = null
let historyRequestToken = 0
const pendingElapsedSeconds = ref(0)
let pendingTimer: number | undefined

function stopPendingTimer() {
  if (pendingTimer !== undefined) {
    window.clearInterval(pendingTimer)
    pendingTimer = undefined
  }
}

function isAbortError(error: unknown): boolean {
  return typeof error === 'object' && error !== null &&
    'name' in error && (error as { name?: unknown }).name === 'AbortError'
}

// ---------- 会话（v0.6.0 会话制；v0.6.2 导航移入左侧栏，会话状态归 store 与侧栏共用） ----------
// 本页不持有会话列表：侧栏操作改 store.sessionView，本页 watch seq 变化后同步重渲染。
// ---------- 建议气泡（v0.6.0）：只存最新一轮的建议 ----------
const suggestions = ref<string[]>([])
const isWelcomeState = computed(() => !messages.value.some(msg => msg.side === 'user'))

const SUBJECT_LABELS: Record<string, string> = {
  chinese: '语文', math: '数学', english: '英语', politics: '道法', history: '历史',
  physics: '物理', chemistry: '化学', geography: '地理', biology: '生物'
}
const WELCOME = () => {
  const subject = SUBJECT_LABELS[auth.activeSubject]
  return `${subject ? `${subject}老师` : '老师'}你好，今天想先了解哪项班级情况？`
}

function createMsg(side: 'ai' | 'user', text: string, pending = false, imageUrl?: string, imageName?: string): Msg {
  return { id: ++seq, side, text, pending, imageUrl, imageName }
}

function pushMsg(
  side: 'ai' | 'user', text: string, pending = false, shouldScroll = true,
  imageUrl?: string, imageName?: string
): Msg {
  const m = createMsg(side, text, pending, imageUrl, imageName)
  messages.value.push(m)
  if (shouldScroll) scrollToBottom()
  return m
}

function createImageUrl(file: File): string {
  const url = URL.createObjectURL(file)
  imageObjectUrls.add(url)
  return url
}

function clearSelectedFile() {
  if (selectedFileUrl.value) {
    if (imagePreview.value?.url === selectedFileUrl.value) closeImagePreview()
    URL.revokeObjectURL(selectedFileUrl.value)
    imageObjectUrls.delete(selectedFileUrl.value)
  }
  selectedFile.value = null
  selectedFileUrl.value = ''
}

function openImagePreview(url: string, alt: string) {
  if (url) imagePreview.value = { url, alt }
}

function closeImagePreview() {
  imagePreview.value = null
}

function onImagePreviewKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && imagePreview.value) closeImagePreview()
}

function onComposerFileSelected(file: File) {
  const isImage = file.type.startsWith('image/')
  const maxBytes = isImage ? 10 * 1024 * 1024 : 100 * 1024 * 1024
  if (file.size > maxBytes) {
    error.value = isImage ? '图片不能超过 10MB，请压缩后再上传。' : '文件不能超过 100MB，请选择较小的文件。'
    return
  }
  if (isImage && !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    error.value = '图片格式不支持，请上传 jpg、png 或 webp 图片。'
    return
  }
  error.value = ''
  knowledgeImportNotice.value = ''
  clearSelectedFile()
  selectedFile.value = file
  selectedFileUrl.value = isImage ? createImageUrl(file) : ''
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

function isAssignmentPublishIntent(text: string): boolean {
  if (/(?:什么时候|何时|是否|有没有|已经|已发布|发布了吗|怎么查看|查询|统计)/u.test(text)) return false
  return /(?:发布|布置|创建|新建|安排|生成).{0,10}(?:作业|练习|题目|习题)|(?:作业|练习|题目|习题).{0,8}(?:发布|布置|创建|生成)|(?:出|生成).{0,5}(?:一|几|多|若干|\d+)?\s*(?:道|套|份)?\s*(?:题|题目|练习|作业)/u.test(text)
}

function splitDraftQuestions(source: string): string[] {
  const text = source.replace(/\r/g, '').trim()
  if (!text) return []
  const lines = text.split('\n')
  const result: string[] = []
  let current = ''
  const numberedLine = /^\s*(?:第\s*\d+\s*[题问]|\d+\s*[.、．)）:]|[（(]\d+[）)])\s*/u
  for (const line of lines) {
    if (numberedLine.test(line) && current.trim()) {
      result.push(current.trim())
      current = line.trim()
    } else {
      current = current ? `${current}\n${line}` : line
    }
  }
  if (current.trim()) result.push(current.trim())
  return result
}

function assignmentDraftFromText(request: string, recognizedText?: string): TeacherAssignmentDraftSeed {
  const titleMatch = request.match(/(?:作业标题|标题)\s*[:：]\s*([^\n]+)/u)
  const requestWithoutTitle = titleMatch ? request.replace(titleMatch[0], '') : request
  let questionText = recognizedText?.trim() ?? ''
  if (questionText) {
    const recognitionLabel = questionText.match(/(?:识别结果|识别内容|图片中的题目(?:如下)?|题目如下)\s*[:：]?\s*/u)
    if (recognitionLabel?.index != null) questionText = questionText.slice(recognitionLabel.index + recognitionLabel[0].length).trim()
    if (/(?:识别失败|暂时无法完成|图片分析失败)/u.test(questionText)) questionText = ''
  } else {
    const markedQuestion = requestWithoutTitle.match(/(?:作业内容|题目内容|题目|题干)\s*(?:如下|是)?\s*[:：]\s*([\s\S]+)/u)
    questionText = markedQuestion?.[1] ?? requestWithoutTitle.replace(
      /^(?:(?:请|帮我|我想|我要|需要)\s*)?(?:发布|布置|创建|新建|安排|生成|出题|出)\s*(?:(?:一份|一个|一套|几道|若干|\d+\s*道)\s*)?(?:新的?)?\s*(?:作业|练习|题目|习题)?\s*[:：,，。；;\s]*/u,
      ''
    )
  }
  return {
    title: titleMatch?.[1]?.trim(),
    questions: splitDraftQuestions(questionText).map((prompt) => ({ prompt }))
  }
}

function imageAssignmentAnalysisPrompt(request: string): string {
  return [
    '教师准备把这张图片里的题目发布成作业。请准确识别并逐题转写题干，保留题号、公式、选项、图表文字和小问，不要解题或给答案。',
    '只输出识别出的题目文本；如果有多题，请按原题号分段。如果局部无法辨认，请在对应位置标注“[不清晰]”。',
    request ? `教师补充：${request}` : ''
  ].filter(Boolean).join('\n')
}

function onWorkflowPublished(message: Msg, assignment: TeacherAssignment) {
  message.workflowDraft = undefined
  message.workflowPublished = assignment.title
  const sessionId = teacher.activeSessionId
  if (sessionId != null) {
    void teacher.recordAssignmentPublishedEvent(sessionId, assignment.id)
      .catch((cause) => console.error('保存作业发布会话事件失败', cause))
      .finally(() => teacher.loadSessions(true))
  } else {
    void teacher.loadSessions(true)
  }
  scrollToBottom()
}

async function sendText(raw: string, attachmentFile?: File) {
  const enteredText = raw.trim()
  if ((!enteredText && !attachmentFile) || sending.value) return
  const text = enteredText || (attachmentFile ? '请阅读并分析这个文件。' : '')
  if (text.length > 2000) {
    error.value = '这条消息有点太长了（最多 2000 字），拆成两条发吧。'
    return
  }
  const publishIntent = isAssignmentPublishIntent(text)
  error.value = ''
  input.value = ''
  suggestions.value = []
  pushMsg('user', text, false, true, undefined, attachmentFile?.name)
  const wait = pushMsg('ai', attachmentFile ? '正在读取文件并查询班级数据' : '正在查询班级数据', true)
  if (publishIntent) {
    wait.workflowDraft = assignmentDraftFromText(text)
    scrollToBottom()
  }
  pendingElapsedSeconds.value = 0
  const pendingStartedAt = Date.now()
  stopPendingTimer()
  pendingTimer = window.setInterval(() => {
    pendingElapsedSeconds.value = Math.floor((Date.now() - pendingStartedAt) / 1000)
  }, 1000)
  const controller = new AbortController()
  activeStreamController = controller
  sending.value = true
  try {
    wait.text = ''
    const extractedAttachment = attachmentFile
      ? await teacher.extractChatAttachment(attachmentFile)
      : undefined
    let receivedCharacter = false
    const res = await teacher.agentChatStream(text, teacher.activeSessionId, (character) => {
      if (!receivedCharacter) {
        wait.text = ''
        wait.pending = false
        stopPendingTimer()
        receivedCharacter = true
      }
      wait.text += character
      scrollToBottom()
    }, controller.signal, extractedAttachment)
    if (res.session_id) teacher.setActiveSession(res.session_id)
    suggestions.value = res.suggestions ?? []
    // 刷新侧栏会话列表（v0.6.2）：首问会生成标题，顺序也按最近更新重排
    teacher.loadSessions(true)
  } catch (e) {
    // 后端会在生成回复前保存用户消息；即使模型失败或请求中断，也刷新侧栏会话。
    void teacher.loadSessions(true)
    if (isAbortError(e)) return
    wait.text = '查询失败：' + (errDetail(e) || '请稍后重试。')
    console.error(e)
  } finally {
    stopPendingTimer()
    if (activeStreamController === controller) activeStreamController = null
    wait.pending = false
    sending.value = false
    scrollToBottom()
  }
}

function sendComposer() {
  if (selectedFile.value?.type.startsWith('image/')) {
    void sendImage(selectedFile.value, input.value.trim())
    return
  }
  if (selectedFile.value) {
    const file = selectedFile.value
    const subject = auth.activeSubject
    if (!Object.prototype.hasOwnProperty.call(SUBJECT_LABELS, subject)) {
      error.value = '当前未选择任教学科，无法确定资料要导入的知识库。'
      return
    }
    clearSelectedFile()
    void importKnowledgeDocument(file, subject as SubjectAgentCode)
    return
  }
  void sendText(input.value)
}

async function importKnowledgeDocument(file: File, subject: SubjectAgentCode) {
  error.value = ''
  knowledgeImportNotice.value = ''
  sending.value = true
  try {
    const job = await teacher.importSubjectKnowledgeDocument(subject, file)
    if (job.duplicate && job.status === 'completed') {
      knowledgeImportNotice.value = `这份资料已在${SUBJECT_LABELS[subject]}知识库中。`
    }
  } catch (cause) {
    // 上传和后台任务进度由应用外壳的全局导入提示持续展示。
    error.value = errDetail(cause) || '资料导入失败，请稍后重试。'
  } finally {
    sending.value = false
  }
}

async function sendImage(file: File, question: string) {
  if (sending.value) return
  if (question.length > 2000) {
    error.value = '这条消息有点太长了（最多 2000 字），请拆成两条发送。'
    return
  }
  const imageUrl = selectedFileUrl.value
  const publishIntent = isAssignmentPublishIntent(question)
  const questionForModel = question || '请分析这张图片。'
  selectedFile.value = null
  selectedFileUrl.value = ''
  input.value = ''
  error.value = ''
  suggestions.value = []
  pushMsg('user', questionForModel, false, true, imageUrl, file.name)
  const wait = pushMsg('ai', '正在分析图片', true)
  pendingElapsedSeconds.value = 0
  const pendingStartedAt = Date.now()
  stopPendingTimer()
  pendingTimer = window.setInterval(() => {
    pendingElapsedSeconds.value = Math.floor((Date.now() - pendingStartedAt) / 1000)
  }, 1000)
  const controller = new AbortController()
  activeStreamController = controller
  sending.value = true
  let receivedText = false
  try {
    let sessionId = teacher.activeSessionId
    if (sessionId == null && teacher.sessionView.fresh) {
      const session = await teacher.createSession()
      sessionId = session.id
      teacher.setActiveSession(session.id)
    }
    const result = await teacher.agentVisionChatStream(
      file, questionForModel, sessionId,
      (text) => {
        if (!receivedText) {
          wait.text = ''
          receivedText = true
        }
        wait.text += text
        wait.pending = false
        scrollToBottom()
      },
      publishIntent ? imageAssignmentAnalysisPrompt(question) : undefined,
      controller.signal
    )
    if (result.session_id) teacher.setActiveSession(result.session_id)
    suggestions.value = result.suggestions ?? []
    void teacher.loadSessions(true)
  } catch (e) {
    if (isAbortError(e)) return
    wait.text = '图片分析失败：' + (errDetail(e) || '请稍后重试。')
    console.error(e)
    void teacher.loadSessions(true)
  } finally {
    if (publishIntent) {
      wait.workflowDraft = assignmentDraftFromText(question, wait.text)
      await nextTick()
      scrollToBottom()
    }
    stopPendingTimer()
    if (activeStreamController === controller) activeStreamController = null
    wait.pending = false
    sending.value = false
    scrollToBottom()
  }
}

onUnmounted(() => {
  stopPendingTimer()
  activeStreamController?.abort()
  window.removeEventListener('keydown', onImagePreviewKeydown)
  imageObjectUrls.forEach((url) => URL.revokeObjectURL(url))
  imageObjectUrls.clear()
})

function historyMessages(rows: AgentHistoryItem[]): Msg[] {
  const restored = rows.map((row) => createMsg(
    row.role === 'user' ? 'user' : 'ai', row.content, false,
    row.image_url ?? undefined, row.image_name ?? row.attachment_name ?? undefined
  ))
  for (let index = 1; index < rows.length; index += 1) {
    const user = rows[index - 1]
    const reply = rows[index]
    if (user.role !== 'user' || reply.role !== 'assistant' || !isAssignmentPublishIntent(user.content)) continue
    restored[index].workflowDraft = assignmentDraftFromText(
      user.content,
      user.image_url ? reply.content : undefined
    )
  }
  for (let index = 0; index < rows.length; index += 1) {
    const event = rows[index]
    if (event.role !== 'assistant') continue
    const published = event.content.match(/^作业发布成功：#\d+《([\s\S]*)》$/u)
    if (!published) continue
    const workflow = restored.slice(0, index).reverse().find((message) => message.workflowDraft)
    if (workflow) {
      workflow.workflowDraft = undefined
      workflow.workflowPublished = published[1]
      restored[index].workflowEventHidden = true
      restored[index].text = ''
    }
  }
  return restored
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
    messages.value = historyMessages(page.items)
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
    const olderMessages = historyMessages(page.items)
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
    clearSelectedFile()
    closeImagePreview()
    input.value = ''
    historyHasMore.value = false
    historyCursor.value = null
    historyLoadError.value = ''
    historyLoadingOlder.value = false
    messages.value = []
    if (view.fresh) {
      renderHistory(null)
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
  window.addEventListener('keydown', onImagePreviewKeydown)
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
/* 对话区保持连续、轻量的页面结构，避免多层卡片和边框分隔 */
.tchat-shell { flex: 1; display: flex; flex-direction: column; height: 100dvh; padding: 20px 28px 22px; }
.tchat-col { flex: 1; display: flex; flex-direction: column; width: 100%; max-width: 960px; margin: 0 auto; min-height: 0; }
.tchat-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
.tchat-head h2 { font-size: 24px; letter-spacing: 0.2px; }

.tchat-panel {
  background: transparent; display: flex; flex-direction: column;
  flex: 1; min-height: 380px; overflow: hidden; position: relative;
}
/* 底部留白给悬浮输入卡让位，最后的消息不被卡片遮住 */
.tchat-body { flex: 1; overflow-y: auto; padding: 18px 20px 118px; }
.tchat-body-welcome { display: flex; flex-direction: column; justify-content: center; align-items: center; padding-bottom: 118px; }
.history-pager { display: flex; flex-direction: column; align-items: center; gap: 6px; margin: 0 0 16px; }
.history-pager-button { border: 1px solid var(--border); border-radius: 999px; padding: 7px 14px; background: var(--card); color: var(--primary); font: inherit; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.history-pager-button:disabled { opacity: 0.55; cursor: wait; }
.history-pager-error { color: var(--red); font-size: 12px; }
.msg-row { display: flex; gap: 10px; margin-bottom: 14px; align-items: flex-start; }
.workflow-event-hidden { display: none; }
.msg-row.user { flex-direction: row-reverse; }
.msg-content { display: flex; flex: 0 1 auto; min-width: 0; max-width: 78%; flex-direction: column; }
.msg-content.has-workflow { width: calc(100% - 40px); max-width: none; flex: 1; }
.msg-row.user .msg-content { align-items: flex-end; }
.msg-avatar {
  width: 30px; height: 30px; border-radius: 50%;
  background: var(--primary-50); color: var(--primary);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 2px;
}
.bubble { border-radius: 14px; padding: 11px 16px; font-size: 14.5px; max-width: 100%; white-space: pre-wrap; word-break: break-word; }
.ai-bubble { background: transparent; border: 0; display: inline-flex; align-items: flex-start; gap: 8px; }
.user-bubble { background: var(--primary); color: #fff; }
.chat-attachment-name { display: inline-flex; max-width: 100%; align-items: center; gap: 6px; margin-top: 5px; overflow-wrap: anywhere; font-size: 12px; opacity: 0.9; }
.chat-workflow { width: 100%; min-width: 0; margin-top: 8px; padding: 4px 14px 14px; border: 1px solid var(--border); border-radius: 16px; background: var(--card); box-shadow: var(--shadow); }
.chat-workflow-success { display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; margin-top: 8px; padding: 12px 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--card); font-size: 13.5px; }
.chat-workflow-success > span, .chat-workflow-success > a { display: inline-flex; align-items: center; gap: 7px; }
.chat-workflow-success > span { color: var(--green); font-weight: 650; }
.chat-workflow-success > a { color: var(--primary); font-weight: 600; }
.message-image { display: block; max-width: min(280px, 66vw); margin: 0 0 6px; padding: 0; overflow: hidden; border: 0; border-radius: 10px; background: transparent; cursor: zoom-in; }
.message-image img { display: block; max-width: 100%; max-height: 220px; object-fit: contain; }
.tchat-body-welcome .msg-row { justify-content: center; width: 100%; margin-bottom: 12px; }
.tchat-body-welcome .msg-avatar { display: none; }
.welcome-bubble { max-width: 100%; padding: 4px 8px; color: var(--text); font-size: 24px; font-weight: 650; line-height: 1.4; text-align: center; }
.welcome-prompts { display: flex; justify-content: center; flex-wrap: wrap; gap: 8px 24px; }
.welcome-prompts button {
  padding: 6px 0; border: 0; background: transparent; color: var(--text-2);
  font: inherit; font-size: 14px; cursor: pointer; transition: color 0.18s ease;
}
.welcome-prompts button:hover:not(:disabled) { color: var(--primary); text-decoration: underline; text-underline-offset: 4px; }
.welcome-prompts button:disabled { opacity: 0.55; cursor: not-allowed; }

/* 建议气泡（v0.6.0）：本轮回复后淡入上浮，stagger 错峰 */
.suggest-row { display: flex; gap: 8px; flex-wrap: wrap; margin: 2px 0 10px 40px; }
.suggest-chip {
  border: 0; background: transparent; color: var(--text-2);
  padding: 6px 0; font-size: 13px; font-weight: 500;
  cursor: pointer; font-family: var(--font);
  animation: suggest-in 0.35s ease both;
  transition: color 0.18s ease;
}
.suggest-chip:hover { color: var(--primary); text-decoration: underline; text-underline-offset: 4px; }
@keyframes suggest-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

.image-lightbox { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: 24px; background: rgba(15,23,42,.82); cursor: zoom-out; }
.image-lightbox > img { display: block; max-width: min(92vw,1200px); max-height: 90vh; object-fit: contain; border-radius: 12px; box-shadow: 0 20px 60px rgba(0,0,0,.4); cursor: default; }
.image-lightbox-close { position: absolute; top: max(16px,env(safe-area-inset-top)); right: max(16px,env(safe-area-inset-right)); display: grid; width: 42px; height: 42px; place-items: center; border: 1px solid rgba(255,255,255,.3); border-radius: 50%; background: rgba(255,255,255,.95); color: #1f2937; cursor: pointer; }
.pending-status { display: inline-flex; align-items: center; gap: 8px; }
.pending-elapsed { color: var(--text-3); font-variant-numeric: tabular-nums; }
.tchat-body-image-composer { padding-bottom: 228px; }
@media (prefers-reduced-motion: reduce) {
  .welcome-prompts button, .suggest-chip { transition: none; }
  .suggest-chip { animation: none; }
}
@media (max-width: 960px) {
  .tchat-shell { height: calc(100dvh - 52px); padding: 14px 14px 16px; }
  .bubble { max-width: 88%; }
  .msg-content { max-width: 88%; }
  .msg-content.has-workflow { width: calc(100% - 40px); max-width: none; }
  .suggest-row { margin-left: 0; }
  .tchat-body { padding-bottom: 112px; }
  .tchat-body-image-composer { padding-bottom: 220px; }
}
</style>
