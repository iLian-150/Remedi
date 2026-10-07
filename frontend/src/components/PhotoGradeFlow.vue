<!-- 拍照批改流程组件（v0.3.0 抽取）：选图 → 转写卡片（可编辑） → 确认批改 → 诊断卡片。
     props.questionId 为归属题目（固定，不再让学生选）；批改完成 emit('graded', 诊断结果)。
     供交作业页原地展开使用；对话页保留其消息流内的同款流程。
     学生端文案口径：批改结果署名统一为「老师批改/批改结果」，不出现「顽固」「置信度」。 -->
<template>
  <div class="pgf">
    <input ref="fileRef" type="file" accept="image/jpeg,image/png,image/webp" hidden @change="onFileChange" />

    <div v-if="phase === 'idle'" class="pgf-idle">
      <button class="btn inline-icon" :disabled="busy" @click="fileRef?.click()">
        <AppIcon name="camera" :size="17" /> 拍照 / 上传作答照片
      </button>
      <span class="hint">把这道题的作答过程拍清楚，一张照片就够了。</span>
    </div>

    <img v-if="previewUrl" :src="previewUrl" alt="作答照片" class="pgf-preview" />

    <p v-if="phase === 'transcribing'" class="pgf-status">
      <AppIcon name="spinner" :size="15" class="spin" /> 正在识别照片里的解题步骤…
    </p>
    <div v-if="errorText" class="error-msg" style="margin-top: 10px">{{ errorText }}</div>

    <!-- 转写卡片 -->
    <div v-if="phase === 'transcribed' || phase === 'submitting' || phase === 'done'" class="pgf-card">
      <p class="pgf-card-title"><AppIcon name="camera" :size="16" /> 照片转写结果</p>
      <p class="hint" style="margin-bottom: 8px">先把照片里的内容转写出来，认错的地方可以直接改，确认无误后点「确认批改」。</p>
      <label class="mini-label">题干</label>
      <input v-model="questionText" type="text" :disabled="confirmed" />
      <label class="mini-label">解题步骤（每行一步，不用写题干）</label>
      <div v-for="(s, i) in steps" :key="i" class="transcribe-step">
        <span class="tnum step-idx">{{ i + 1 }}</span>
        <input v-model="steps[i]" type="text" :disabled="confirmed" />
        <button class="icon-btn" title="删除这一步" :disabled="confirmed" @click="steps.splice(i, 1)">
          <AppIcon name="x" :size="15" />
        </button>
      </div>
      <button class="btn small secondary inline-icon" :disabled="confirmed" @click="steps.push('')">
        <AppIcon name="plus" :size="14" /> 添加一步
      </button>
      <div class="toolbar" style="margin: 12px 0 0">
        <button class="btn" :disabled="confirmed || phase === 'submitting'" @click="confirm">
          {{ confirmed ? '已批改' : phase === 'submitting' ? '批改中…' : '确认批改' }}
        </button>
        <button v-if="phase === 'done'" class="btn secondary" @click="reset">再拍一张</button>
      </div>
    </div>

    <!-- 诊断卡片（老师批改结果） -->
    <div v-if="phase === 'done' && result" class="pgf-card">
      <p class="pgf-card-title">
        <AppIcon name="check" :size="16" /> 老师批改结果
        <span v-if="questionStem" class="badge badge-blue">{{ questionStem }}</span>
      </p>
      <div
        v-for="st in result.steps"
        :key="st.seq"
        class="diag-step"
        :class="{ 'first-error': st.status === 'error', correct: st.status === 'ok' }"
      >
        <span class="diag-icon" :class="st.status"><AppIcon :name="stepIcon(st.status)" :size="14" /></span>
        <div class="diag-step-main">
          <div class="step-title">{{ st.seq === 0 ? '题干' : `步骤 ${st.seq}` }} · {{ STEP_STATUS_TEXT[st.status] }}</div>
          <p>{{ st.text }}</p>
        </div>
      </div>

      <template v-if="result.errors.length">
        <div v-for="e in result.errors" :key="e.id" class="error-item">
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
      <p v-else class="ok-line"><AppIcon name="check" :size="15" /> 太棒了，这道题全部正确，继续保持！</p>

      <!-- 追问（v0.4.0）：先想一想，再看解析 -->
      <div v-if="result.follow_up_question" class="followup-box">
        <span class="followup-icon"><AppIcon name="lightbulb" :size="15" /></span>
        <p><b>想一想：</b>{{ result.follow_up_question }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useStudentStore } from '../stores/student'
import type { StepStatus, SubmissionResult } from '../api/types'
import { STEP_STATUS_TEXT } from '../api/types'
import { sanitizeStudentCopy } from '../utils/errorType'
import AppIcon from './icons/AppIcon.vue'
import type { IconName } from './icons/paths'
import ErrorTypeBadge from './ErrorTypeBadge.vue'

const props = defineProps<{
  questionId: number
  questionStem?: string
}>()
const emit = defineEmits<{ (e: 'graded', result: SubmissionResult): void }>()

const student = useStudentStore()

type Phase = 'idle' | 'transcribing' | 'transcribed' | 'submitting' | 'done'
const phase = ref<Phase>('idle')
const busy = ref(false)
const fileRef = ref<HTMLInputElement | null>(null)
const previewUrl = ref('')
const errorText = ref('')
const questionText = ref('')
const steps = ref<string[]>([])
const confirmed = ref(false)
const result = ref<SubmissionResult | null>(null)

function stepIcon(s: StepStatus): IconName {
  return { stem: 'file', ok: 'check', error: 'x', unparseable: 'help', skipped: 'minus' }[s] as IconName
}

function errDetail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof d === 'string' ? d : ''
}

async function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  errorText.value = ''
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    errorText.value = '这张图片格式不对，请上传 jpg / png / webp 格式的作答照片。'
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    errorText.value = '图片太大了（超过 10MB），请压缩后再试。'
    return
  }
  previewUrl.value = URL.createObjectURL(file)
  phase.value = 'transcribing'
  busy.value = true
  try {
    const res = await student.transcribePhoto(file)
    questionText.value = res.question_text
    steps.value = [...res.steps]
    phase.value = 'transcribed'
  } catch (err) {
    phase.value = 'idle'
    errorText.value = '识别失败：' + (errDetail(err) || '请稍后重试。')
    console.error(err)
  } finally {
    busy.value = false
  }
}

async function confirm() {
  const cleaned = steps.value.map((s) => s.trim()).filter(Boolean)
  if (!cleaned.length) {
    errorText.value = '转写卡片里的步骤是空的，先补上步骤再确认批改。'
    return
  }
  errorText.value = ''
  phase.value = 'submitting'
  try {
    const res = await student.submitMath({ question_id: props.questionId, steps: cleaned })
    result.value = res
    confirmed.value = true
    phase.value = 'done'
    emit('graded', res)
  } catch (e) {
    phase.value = 'transcribed'
    errorText.value = '批改失败：' + (errDetail(e) || '请稍后重试。')
    console.error(e)
  }
}

function reset() {
  phase.value = 'idle'
  previewUrl.value = ''
  questionText.value = ''
  steps.value = []
  confirmed.value = false
  result.value = null
  errorText.value = ''
}
</script>

<style scoped>
.pgf { margin-top: 12px; }
.pgf-idle { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.pgf-preview { max-width: 300px; max-height: 340px; border-radius: 10px; border: 1px solid var(--border); display: block; margin-bottom: 10px; }
.pgf-status { display: inline-flex; align-items: center; gap: 7px; font-size: 14px; color: var(--text-2); padding: 8px 0; }
.pgf-card {
  background: var(--card); border: 1px solid #EDF0F4; border-radius: 12px;
  box-shadow: var(--shadow); padding: 14px 16px; margin-top: 10px;
}
.pgf-card-title { font-size: 14.5px; font-weight: 700; display: flex; align-items: center; gap: 7px; margin-bottom: 8px; flex-wrap: wrap; }
.mini-label { display: block; font-size: 13px; color: var(--text-2); margin: 10px 0 5px; }
.transcribe-step { display: flex; align-items: center; gap: 8px; margin-bottom: 7px; }
.transcribe-step .step-idx { min-width: 18px; text-align: right; color: var(--text-3); font-size: 13px; }
.diag-step {
  display: flex; gap: 9px;
  border: 1px solid var(--border); border-left: 4px solid #D1D5DB;
  border-radius: 8px; padding: 9px 12px; margin-bottom: 7px; background: #fff;
}
.diag-step.first-error { border-left-color: var(--red); background: #FFFBFB; }
.diag-step.correct { border-left-color: var(--green); }
.diag-icon { width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex-shrink: 0; background: var(--gray-bg); color: var(--gray); }
.diag-icon.ok { background: var(--green-bg); color: var(--green); }
.diag-icon.error { background: var(--red-bg); color: var(--red); }
.diag-icon.unparseable { background: var(--amber-bg); color: var(--amber); }
.diag-step-main { flex: 1; min-width: 0; }
.diag-step .step-title { font-weight: 600; font-size: 12.5px; color: var(--text-3); margin-bottom: 2px; }
.diag-step.first-error .step-title { color: #991B1B; }
.diag-step.correct .step-title { color: #065F46; }
.error-item { margin-top: 12px; padding-top: 11px; border-top: 1px solid #F1F3F6; }
.encourage { margin-top: 7px; font-size: 14px; }
.detail { margin-top: 5px; font-size: 14px; color: var(--text-2); }
.ok-line { margin-top: 9px; font-size: 14.5px; color: #065F46; display: flex; align-items: center; gap: 6px; }
.followup-box {
  display: flex; gap: 9px; align-items: flex-start;
  background: var(--primary-50); border: 1px solid #DBEAFE; border-radius: 10px;
  padding: 11px 14px; margin-top: 12px; font-size: 14px;
}
.followup-icon {
  width: 25px; height: 25px; border-radius: 50%; flex-shrink: 0;
  background: var(--primary); color: #fff;
  display: flex; align-items: center; justify-content: center;
}
.followup-box p { padding-top: 2px; }
.spin { animation: pgf-spin 1s linear infinite; }
@keyframes pgf-spin { to { transform: rotate(360deg); } }
</style>
