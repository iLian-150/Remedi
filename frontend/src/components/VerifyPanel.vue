<!-- 二次验证作答面板（v0.4.0）：在学习报告页内嵌展开。
     打开即为该知识点创建（或复用未完成的）一道变式题；作答两种方式：
       拍照 → 转写 → 步骤自动填入下方可编辑框；或直接逐行填写步骤。
     提交后按步骤展示判定结果；通过时 emit('passed')，报告页据此刷新
     知识点状态与修复进度；失败可「再试一次」（同一道题重做）或
     「换一道题」（新建一条验证）。学生端口径：不出现「置信度」等术语。 -->
<template>
  <div class="verify-panel">
    <div class="vp-head">
      <p class="vp-title"><AppIcon name="target" :size="17" /> 二次验证 · {{ knowledgePoint }}</p>
      <button class="icon-btn" aria-label="收起验证" title="收起验证" @click="emit('close')"><AppIcon name="x" :size="16" /></button>
    </div>
    <p class="hint" style="margin-bottom: 10px">
      订正对了还不算真正掌握——独立做对这道同类题，这个知识点就修复啦。
    </p>

    <div v-if="loading" class="loading" style="padding: 18px 0">正在为你准备一道同类题…</div>
    <div v-if="errorText" class="error-msg">{{ errorText }}</div>

    <template v-if="verification && !loading">
      <div class="vp-prompt">
        <span class="vp-prompt-label">题目</span>
        <span class="vp-prompt-text">{{ verification.prompt }}</span>
      </div>

      <input ref="fileRef" type="file" accept="image/jpeg,image/png,image/webp" hidden @change="onFileChange" />
      <div class="vp-photo-row">
        <button class="btn small secondary inline-icon" :disabled="transcribing || passed" @click="fileRef?.click()">
          <AppIcon name="camera" :size="15" /> {{ transcribing ? '识别中…' : '拍照识别我的手写过程' }}
        </button>
        <span class="hint">也可以直接在下面逐行写步骤。</span>
      </div>

      <label class="mini-label">我的解题步骤（每行一步，第一行先抄一遍原题的式子）</label>
      <div v-for="(s, i) in steps" :key="i" class="vp-step-row">
        <span class="tnum step-idx">{{ i + 1 }}</span>
        <input v-model="steps[i]" type="text" :disabled="passed" :placeholder="i === 0 ? '例如：2x+3=7' : ''" />
        <button class="icon-btn" :aria-label="`删除第 ${i + 1} 步`" title="删除这一步" :disabled="passed" @click="steps.splice(i, 1)">
          <AppIcon name="x" :size="15" />
        </button>
      </div>
      <button class="btn small secondary inline-icon" :disabled="passed" @click="steps.push('')">
        <AppIcon name="plus" :size="14" /> 添加一步
      </button>

      <!-- 判定结果 -->
      <template v-if="result">
        <div class="vp-result-steps">
          <div
            v-for="st in result.steps"
            :key="st.seq"
            class="diag-step"
            :class="{ 'first-error': st.status === 'error', correct: st.status === 'ok' }"
          >
            <span class="diag-icon" :class="st.status"><AppIcon :name="stepIcon(st.status)" :size="13" /></span>
            <div class="diag-step-main">
              <div class="step-title">步骤 {{ st.seq }} · {{ STEP_STATUS_TEXT[st.status] }}</div>
              <p>{{ st.text }}</p>
            </div>
          </div>
        </div>
        <div v-if="result.passed" class="vp-passed">
          <span class="vp-passed-icon"><AppIcon name="check" :size="18" /></span>
          <div>
            <p class="vp-passed-title">验证通过，这个知识点修复啦！</p>
            <p class="vp-passed-line">{{ result.detail }}</p>
          </div>
        </div>
        <div v-else class="vp-failed">
          <p>
            <ErrorTypeBadge v-if="result.error_type" :type="result.error_type as ErrorType" />
            <span class="badge badge-amber">第 {{ result.first_error_seq }} 步需要再想想</span>
          </p>
          <p class="detail"><strong>解析：</strong>{{ result.detail }}</p>
        </div>
      </template>

      <div class="toolbar" style="margin: 14px 0 0">
        <button v-if="!passed" class="btn" :disabled="submitting" @click="submit">
          {{ submitting ? '判定中…' : result ? '再提交一次' : '提交验证' }}
        </button>
        <button v-if="result && !result.passed" class="btn secondary" :disabled="submitting" @click="newVariant">
          换一道题
        </button>
        <button v-if="passed" class="btn" @click="emit('close')">完成</button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useStudentStore } from '../stores/student'
import type { ErrorType, StepStatus, Verification, VerificationSubmitResult } from '../api/types'
import { STEP_STATUS_TEXT } from '../api/types'
import AppIcon from './icons/AppIcon.vue'
import type { IconName } from './icons/paths'
import ErrorTypeBadge from './ErrorTypeBadge.vue'

const props = defineProps<{
  knowledgePoint: string
  subject?: string
  sourceErrorId?: number
}>()
const emit = defineEmits<{ (e: 'passed'): void; (e: 'close'): void }>()

const student = useStudentStore()

const verification = ref<Verification | null>(null)
const steps = ref<string[]>([''])
const result = ref<VerificationSubmitResult | null>(null)
const loading = ref(false)
const submitting = ref(false)
const transcribing = ref(false)
const errorText = ref('')
const fileRef = ref<HTMLInputElement | null>(null)

const passed = computed(() => result.value?.passed === true || verification.value?.status === 'passed')

function stepIcon(s: StepStatus): IconName {
  return { stem: 'file', ok: 'check', error: 'x', unparseable: 'help', skipped: 'minus' }[s] as IconName
}

function errDetail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof d === 'string' ? d : ''
}

async function load() {
  loading.value = true
  errorText.value = ''
  result.value = null
  steps.value = ['']
  try {
    verification.value = await student.createVerification({
      knowledge_point: props.knowledgePoint,
      subject: props.subject,
      source_error_id: props.sourceErrorId
    })
  } catch (e) {
    errorText.value = '同类题准备失败：' + (errDetail(e) || '请稍后重试。')
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function newVariant() {
  // 当前记录已是 failed（非 pending），后端会新建一条并生成新题
  verification.value = null
  await load()
}

async function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    errorText.value = '这张图片格式不对，请上传 jpg / png / webp 格式的照片。'
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    errorText.value = '图片太大了（超过 10MB），请压缩后再试。'
    return
  }
  errorText.value = ''
  transcribing.value = true
  try {
    const res = await student.transcribePhoto(file)
    if (res.steps.length) steps.value = [...res.steps]
  } catch (err) {
    errorText.value = '识别失败：' + (errDetail(err) || '请稍后重试，也可以直接在下面写步骤。')
    console.error(err)
  } finally {
    transcribing.value = false
  }
}

async function submit() {
  if (!verification.value) return
  const cleaned = steps.value.map((s) => s.trim()).filter(Boolean)
  if (!cleaned.length) {
    errorText.value = '先把解题步骤写下来，再提交验证。'
    return
  }
  errorText.value = ''
  submitting.value = true
  try {
    result.value = await student.submitVerification(verification.value.id, cleaned)
    if (result.value.passed) {
      verification.value = { ...verification.value, status: 'passed', attempts: result.value.attempts }
      emit('passed')
    }
  } catch (e) {
    errorText.value = '提交失败：' + (errDetail(e) || '请稍后重试。')
    console.error(e)
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.verify-panel {
  background: var(--primary-50);
  border: 1px solid #DBEAFE;
  border-radius: 12px;
  padding: 16px 18px;
}
.vp-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.vp-title { font-size: 15.5px; font-weight: 700; display: flex; align-items: center; gap: 7px; color: var(--primary-dark); }
.vp-prompt {
  display: flex; gap: 10px; align-items: baseline;
  background: #fff; border: 1px solid #DBEAFE; border-radius: 10px;
  padding: 11px 14px; margin-bottom: 12px;
}
.vp-prompt-label {
  font-size: 12px; font-weight: 700; color: var(--primary);
  background: var(--primary-50); border-radius: 6px; padding: 2px 8px; flex-shrink: 0;
}
.vp-prompt-text { font-size: 15.5px; font-weight: 600; }
.vp-photo-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 4px; }
.mini-label { display: block; font-size: 13px; color: var(--text-2); margin: 10px 0 6px; }
.vp-step-row { display: flex; align-items: center; gap: 8px; margin-bottom: 7px; }
.vp-step-row .step-idx { min-width: 18px; text-align: right; color: var(--text-3); font-size: 13px; }
.vp-result-steps { margin-top: 14px; }
.diag-step {
  display: flex; gap: 9px;
  border: 1px solid var(--border); border-left: 4px solid #D1D5DB;
  border-radius: 8px; padding: 8px 12px; margin-bottom: 7px; background: #fff;
}
.diag-step.first-error { border-left-color: var(--red); background: #FFFBFB; }
.diag-step.correct { border-left-color: var(--green); }
.diag-icon { width: 21px; height: 21px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex-shrink: 0; background: var(--gray-bg); color: var(--gray); }
.diag-icon.ok { background: var(--green-bg); color: var(--green); }
.diag-icon.error { background: var(--red-bg); color: var(--red); }
.diag-icon.unparseable { background: var(--amber-bg); color: var(--amber); }
.diag-step-main { flex: 1; min-width: 0; }
.diag-step .step-title { font-weight: 600; font-size: 12.5px; color: var(--text-3); margin-bottom: 1px; }
.diag-step.first-error .step-title { color: #991B1B; }
.diag-step.correct .step-title { color: #065F46; }
.vp-passed {
  display: flex; gap: 11px; align-items: flex-start;
  background: var(--green-bg); border-radius: 10px; padding: 12px 14px; margin-top: 12px;
}
.vp-passed-icon {
  width: 34px; height: 34px; border-radius: 50%; flex-shrink: 0;
  background: var(--green); color: #fff;
  display: flex; align-items: center; justify-content: center;
}
.vp-passed-title { font-size: 14.5px; font-weight: 700; color: #065F46; }
.vp-passed-line { font-size: 13.5px; color: #065F46; }
.vp-failed { margin-top: 12px; background: #fff; border: 1px solid #FDE68A; border-radius: 10px; padding: 12px 14px; }
.vp-failed .detail { margin-top: 7px; font-size: 14px; color: var(--text-2); }
</style>
