<template>
  <aside class="mistake-point-assistant" :class="{ 'is-fullscreen': fullscreen }" :aria-label="`${mistake.category_label}专属问答`">
    <header class="mistake-point-assistant-head">
      <div>
        <span>{{ mistake.source_kind === 'student_saved' ? '自主收录题目' : '错题专属问答' }}</span>
        <h2>{{ mistake.source_kind === 'student_saved' ? '继续复习这道题' : mistake.category_label || mistake.error_type }}</h2>
        <p>{{ mistake.knowledge_point }} · {{ subjectName(mistake.question_subject) }}</p>
      </div>
      <nav class="mistake-point-assistant-controls" aria-label="内容区布局控制">
        <button type="button" aria-label="左右交换区域" title="左右交换区域" @click="$emit('swap')">⇄</button>
        <button type="button" :aria-label="fullscreen ? '退出全屏' : '全屏显示'" :title="fullscreen ? '退出全屏' : '全屏显示'" @click="$emit('fullscreen')">⛶</button>
        <button type="button" class="mistake-point-assistant-close" aria-label="关闭错误点问答" title="关闭" @click="$emit('close')">×</button>
      </nav>
    </header>

    <section class="mistake-point-summary" :class="{ 'is-collapsed': summaryCollapsed }" :aria-label="mistake.source_kind === 'student_saved' ? '收录题目' : '错误点内容'">
      <div class="mistake-point-summary-title">
        <div class="mistake-point-summary-heading">
          <strong>{{ mistake.source_kind === 'student_saved' ? '收录题目' : '错误点内容' }}</strong>
          <span v-if="summaryCollapsed">{{ mistake.source_kind === 'student_saved' ? mistake.question_stem : `第 ${mistake.question_order} 题 · ${mistake.question_stem}` }}</span>
        </div>
        <div class="mistake-point-summary-tools">
          <small v-if="mistake.source_kind === 'student_saved'">这是你主动加入错题本的题目</small>
          <small v-else>{{ related.length }} 道相关错题 · 本作业已学 {{ progress.completed }}/{{ progress.total }} 个错误点</small>
          <button type="button" class="mistake-point-summary-toggle" :aria-expanded="!summaryCollapsed" :aria-label="summaryCollapsed ? '展开错误点内容' : '收起错误点内容'" @click="summaryCollapsed = !summaryCollapsed">
            <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m4.5 12.5 5.5-5.5 5.5 5.5" /></svg>
          </button>
        </div>
      </div>
      <div v-if="!summaryCollapsed" class="mistake-point-summary-body" id="mistake-point-summary-body">
        <div class="mistake-point-summary-detail">
          <div class="mistake-point-summary-detail-head">
            <span>{{ mistake.source_kind === 'student_saved' ? '自主收录' : `第 ${mistake.question_order} 题${mistake.step_seq ? ` · 第 ${mistake.step_seq} 步` : ''}` }}</span>
            <strong>{{ mistake.category_label || mistake.error_type }}</strong>
          </div>
          <div class="mistake-reference-line"><span>题目</span><p>{{ mistake.question_stem || '题目内容暂未记录' }}</p></div>
          <a v-if="mistake.image_url" class="mistake-capture-image-link" :href="imageHref(mistake.image_url)" target="_blank" rel="noreferrer">查看上传原图 →</a>
          <div v-if="mistake.step_text" class="mistake-reference-line"><span>作答</span><p>{{ mistake.step_text }}</p></div>
          <div class="mistake-point-summary-markdown">{{ safe(mistake.detail || '回顾这类错误的作答过程，找到容易忽略的条件。') }}</div>
          <div v-if="mistake.latest_correction?.content" class="mistake-reference-line correction"><span>订正</span><p>{{ mistake.latest_correction.content }}</p></div>
        </div>
        <small>{{ mistake.source_kind === 'student_saved' ? '由你主动加入错题本' : `来自 ${mistake.assignment_title}` }}</small>
        <div v-if="mistake.source_kind !== 'student_saved' && related.length > 1" class="mistake-point-related-assignments">
          <strong>同类错误出现在 {{ related.length }} 道错题中</strong>
          <div v-for="item in related" :key="item.id">
            <span>第 {{ item.question_order }} 题 · {{ item.assignment_title }}<template v-if="item.id === mistake.id"> · 当前错题</template></span>
            <button type="button" @click="$emit('review', item)">查看原题</button>
          </div>
        </div>
        <div class="mistake-point-summary-actions">
          <template v-if="mistake.source_kind !== 'student_saved'">
            <button type="button" @click="$emit('review', mistake)">查看原题</button>
            <button type="button" class="study" :disabled="savingStudy" @click="$emit('study')">{{ savingStudy ? '保存中…' : mistake.category_studied ? '已学会 · 撤销' : '学完这个错误点' }}</button>
          </template>
          <span v-else>已保存在错题本，可以继续和学习助手讨论。</span>
        </div>
      </div>
    </section>

    <div v-if="mistake.source_kind !== 'student_saved' && progress.complete" class="mistake-point-assignment-complete" role="status">✓ 这份作业的所有错误点和知识点都已学完。</div>
    <div class="mistake-point-chat-title"><strong>一起弄懂这道题</strong><span>从你卡住的地方开始</span></div>
    <div class="mistake-point-transcript" aria-live="polite">
      <div v-if="messages.length === 0" class="mistake-point-empty">
        <div class="mistake-point-empty-intro">
          <span class="mistake-point-book-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M12 6.5C9.8 4.8 6.8 4.4 3.5 5.2v13c3.3-.8 6.3-.4 8.5 1.3m0-13c2.2-1.7 5.2-2.1 8.5-1.3v13c-3.3-.8-6.3-.4-8.5 1.3m0-13v13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" /></svg></span>
          <div><strong>想从哪里问起？</strong><p>错因、解题思路，或者再练一道相似题，都可以慢慢聊。</p></div>
        </div>
        <div class="mistake-point-quick-questions" aria-label="常见问题">
          <button v-for="prompt in prompts" :key="prompt" type="button" @click="question = prompt">{{ prompt }}</button>
        </div>
      </div>
      <article v-for="(message, index) in messages" :key="`${index}-${message.role}`" class="mistake-point-message" :class="message.role">
        <template v-if="message.role === 'assistant'"><strong>知行 · 思路讲解</strong><p>{{ message.content || (sending ? '正在整理思路…' : '') }}</p></template>
        <p v-else>{{ message.content }}</p>
      </article>
      <p v-if="error" class="mistake-point-chat-error" role="alert">{{ error }}</p>
    </div>
    <form class="mistake-point-composer" @submit.prevent="sendQuestion">
      <div class="mistake-point-composer-inner">
        <textarea v-model="question" placeholder="写下你卡住的地方…" rows="2" :disabled="sending" @keydown.enter.exact.prevent="sendQuestion" />
        <button type="submit" :disabled="!question.trim() || sending">{{ sending ? '讲解中…' : '提问' }}</button>
      </div>
    </form>
  </aside>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useStudentStore } from '../../stores/student'
import type { StudentMistake } from '../../api/types'
import { sanitizeStudentCopy } from '../../utils/errorType'

const props = defineProps<{
  mistake: StudentMistake
  related: StudentMistake[]
  progress: { completed: number; total: number; complete: boolean }
  savingStudy?: boolean
  fullscreen?: boolean
}>()
defineEmits<{
  close: []
  swap: []
  fullscreen: []
  review: [mistake: StudentMistake]
  study: []
}>()

const student = useStudentStore()
const prompts = ['为什么会错？', '这一步怎么想？', '出一道相似题']
const question = ref('')
const messages = ref<Array<{ role: 'user' | 'assistant'; content: string }>>([])
const sending = ref(false)
const summaryCollapsed = ref(false)
const error = ref('')

watch(() => props.mistake.id, () => {
  question.value = ''
  messages.value = []
  error.value = ''
  summaryCollapsed.value = false
})

function subjectName(value: string) {
  const labels: Record<string, string> = { math: '数学', english: '英语作文', physics: '物理', chemistry: '化学', chinese: '语文', biology: '生物' }
  return labels[value] || value || '其他学科'
}
function safe(value: string) { return sanitizeStudentCopy(value) }
function imageHref(value: string) {
  const base = import.meta.env.VITE_API_BASE_URL || ''
  return base ? `${base.replace(/\/+$/, '')}${value}` : value
}

async function sendQuestion() {
  const text = question.value.trim()
  if (!text || sending.value) return
  const context = [
    `请围绕这道错题回答学生的问题。学科：${subjectName(props.mistake.question_subject)}。`,
    `知识点：${props.mistake.knowledge_point}；错误类别：${props.mistake.category_label}。`,
    `题目：${props.mistake.question_stem}`,
    props.mistake.step_text ? `学生作答：${props.mistake.step_text}` : '',
    props.mistake.detail ? `诊断说明：${safe(props.mistake.detail)}` : '',
    `学生问题：${text}`
  ].filter(Boolean).join('\n')
  messages.value.push({ role: 'user', content: text }, { role: 'assistant', content: '' })
  question.value = ''
  error.value = ''
  sending.value = true
  summaryCollapsed.value = true
  try {
    const result = await student.agentChat(context)
    messages.value[messages.value.length - 1].content = result.reply
  } catch {
    messages.value.pop()
    question.value = text
    error.value = '暂时无法回答，请确认学习助手服务可用后重试。'
  } finally {
    sending.value = false
  }
}
</script>

<style scoped>
.mistake-reference-line { display: grid; grid-template-columns: 32px minmax(0, 1fr); gap: 8px; align-items: start; margin: 9px 0; color: #7c8478; font-size: 12px; }
.mistake-reference-line p { margin: 0; color: #596257; white-space: pre-wrap; overflow-wrap: anywhere; }
.mistake-reference-line.correction p { color: #4f7658; }
.mistake-point-summary-detail-head span { color: #879084; }
.mistake-point-summary-detail-head strong { color: #547258; }
.mistake-point-summary-markdown { margin-top: 10px; color: #768073; font-size: 12px; line-height: 1.65; white-space: pre-wrap; }
.mistake-point-summary-markdown p { margin: 0; }
.mistake-capture-image-link { display: inline-block; margin: 6px 0 10px; color: #55765c; font-size: 12px; font-weight: 600; text-decoration: none; }
.mistake-point-transcript { overflow-y: auto; }
.mistake-point-message p { margin: 6px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.mistake-point-composer textarea { resize: vertical; }
</style>
