<!-- 拍照批改流程组件（v0.3.0 抽取）：选图 → 转写卡片（可编辑） → 确认批改 → 诊断卡片。
     props.questionId 为归属题目（固定，不再让学生选）；批改完成 emit('graded', 诊断结果)。
     供交作业页原地展开使用；对话页保留其消息流内的同款流程。
     v0.6.0 新增 direct 模式（交作业页用）：选完照片自动转写并立刻提交诊断，
     不再出现转写确认这一步，直接出诊断卡；诊断卡上保留补救——展示识别到的
     步骤原文，并可展开原编辑器修改后重新提交。对话页仍用默认确认模式。
     v0.9.2：点按直达图库——组件内不再有「先展开面板再点一次选图」的中间层：
     父级按钮点击时调 openPicker()（defineExpose）当下就打开系统图库/文件选择；
     未选图取消则组件保持 idle 且不渲染任何可见内容；「再拍一张/重新选图」同理直达。
     学生端文案口径：系统评分即时展示，整份作业低于 60 分才进入教师复核。 -->
<template>
  <div class="pgf">
    <input ref="fileRef" type="file" accept="image/*" hidden @change="onFileChange" />

    <img v-if="previewUrl" :src="previewUrl" alt="作答照片" class="pgf-preview" />

    <p v-if="phase === 'transcribing' || (direct && phase === 'submitting')" class="pgf-status">
      <AppIcon name="spinner" :size="15" class="spin" /> {{ direct ? '正在识别并批改…' : '正在识别照片里的解题步骤…' }}
    </p>
    <div v-if="errorText" class="error-msg" style="margin-top: 10px">{{ errorText }}</div>

    <div v-if="phase === 'answered'" class="pgf-card">
      <p class="pgf-card-title"><AppIcon name="book" :size="16" /> 先看题目讲解</p>
      <p class="pgf-answer-question">{{ questionText }}</p>
      <p class="pgf-answer-copy">{{ answerText }}</p>
      <button class="btn small secondary" :disabled="busy || savingCapture || savedCapture || !answerText.trim()" @click="saveCapture">
        {{ savedCapture ? '已加入错题本' : savingCapture ? '正在收录…' : '加入错题本' }}
      </button>
    </div>

    <!-- 转写卡片（direct 模式默认不出现，仅在诊断卡里展开「修改重交」时显示） -->
    <div v-if="cardVisible" class="pgf-card">
      <p class="pgf-card-title"><AppIcon name="camera" :size="16" /> 照片转写结果</p>
      <p class="hint" style="margin-bottom: 8px">先把照片里的内容转写出来，认错的地方可以直接改，确认无误后点「确认批改」。</p>
      <label class="mini-label">题干</label>
      <input v-model="questionText" type="text" :disabled="confirmed && !fixOpen" />
      <label class="mini-label">解题步骤（每行一步，不用写题干）</label>
      <div v-for="(s, i) in steps" :key="i" class="transcribe-step">
        <span class="tnum step-idx">{{ i + 1 }}</span>
        <input v-model="steps[i]" type="text" :disabled="confirmed && !fixOpen" />
        <button class="icon-btn" :aria-label="`删除第 ${i + 1} 步`" title="删除这一步" :disabled="confirmed && !fixOpen" @click="steps.splice(i, 1)">
          <AppIcon name="x" :size="15" />
        </button>
      </div>
      <button class="btn small secondary inline-icon" :disabled="confirmed && !fixOpen" @click="steps.push('')">
        <AppIcon name="plus" :size="14" /> 添加一步
      </button>
      <div class="toolbar" style="margin: 12px 0 0">
        <button class="btn" :disabled="(confirmed && !fixOpen) || phase === 'submitting'" @click="confirm">
          {{ phase === 'submitting' ? '批改中…' : fixOpen ? '重新提交批改' : confirmed ? '已批改' : '确认批改' }}
        </button>
        <button v-if="fixOpen" class="btn secondary" @click="fixOpen = false">收起修改</button>
        <button v-if="phase === 'done' && !fixOpen" class="btn secondary" @click="retake">再拍一张</button>
      </div>
    </div>

    <!-- 诊断、评分和错题即时展示；整份作业低于 60 分才进入教师复核 -->
    <div v-if="phase === 'done' && result" class="pgf-card">
      <p class="pgf-card-title">
        <AppIcon :name="result.status === 'pending_review' ? 'history' : 'check'" :size="16" />
        {{ result.status === 'pending_review' ? '诊断已生成 · 老师复核中' : '老师批改结果' }}
        <span v-if="questionStem" class="badge badge-blue">{{ questionStem }}</span>
      </p>
      <div v-if="result.status === 'pending_review'" class="review-pending-box">
        <span class="review-pending-icon"><AppIcon name="history" :size="17" /></span>
        <div>
          <p class="review-pending-title">错题已同步加入错题本和订正区</p>
          <p class="review-pending-sub">这份作业总分低于 60 分，老师正在审核；错题和订正任务已同步，你可以先继续订正。</p>
        </div>
      </div>
      <p v-if="result.score" class="score-line">
        本题 {{ result.score.score }} / {{ result.score.max_score }} 分
        <span v-if="result.score.assignment_score !== null && result.score.assignment_score !== undefined">
          · 作业目前 {{ result.score.assignment_score }} / {{ result.score.assignment_total ?? 0 }} 分
        </span>
      </p>
      <template v-if="result.steps.length || result.errors.length">
      <p v-if="result.errors.length" class="pgf-auto-booked">发现 {{ result.errors.length }} 个错误点，已自动加入错题本。</p>
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
          <p v-if="e.detail" class="detail"><strong>解析：</strong>{{ sanitizeStudentCopy(e.detail) }}</p>
          <div class="toolbar" style="margin-top: 8px; margin-bottom: 0">
            <router-link to="/student/corrections" class="btn small secondary">去订正这道题</router-link>
          </div>
        </div>
      </template>
      <p v-else class="ok-line"><AppIcon name="check" :size="15" /> 太棒了，这道题全部正确，继续保持！</p>

      <!-- 追问（v0.4.0）：先想一想，再看解析 -->
      <div v-if="result.follow_up_question" class="followup-box">
        <span class="followup-icon"><AppIcon name="lightbulb" :size="15" /></span>
        <p><b>想一想：</b>{{ result.follow_up_question }}</p>
      </div>
      </template>

      <!-- direct 模式补救（v0.6.0）：展示本次识别到的步骤原文，可展开编辑器改后重交 -->
      <div v-if="direct" class="fix-box">
        <p class="fix-title">这次是按下面这些步骤批改的（照片识别结果）：</p>
        <ol class="fix-steps">
          <li v-for="(s, i) in steps" :key="i">{{ s }}</li>
        </ol>
        <button v-if="!fixOpen" class="btn small secondary" @click="fixOpen = true">
          识别不准？展开修改并重新提交
        </button>
        <button class="btn small ghost" style="margin-left: 8px" @click="retake">再拍一张</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useStudentStore } from '../stores/student'
import type { StepStatus, SubmissionResult } from '../api/types'
import { STEP_STATUS_TEXT } from '../api/types'
import { sanitizeStudentCopy } from '../utils/errorType'
import AppIcon from './icons/AppIcon.vue'
import type { IconName } from './icons/paths'
import ErrorTypeBadge from './ErrorTypeBadge.vue'

const props = withDefaults(
  defineProps<{
    questionId: number
    questionStem?: string
    /** v0.6.0：direct 模式——选完照片自动转写并立刻提交诊断，跳过转写确认步 */
    direct?: boolean
  }>(),
  { direct: false }
)
const emit = defineEmits<{
  (e: 'graded', result: SubmissionResult): void
  /** v0.9.2：流程是否已离开 idle（父级据此切换按钮文案与收起控制） */
  (e: 'active', active: boolean): void
}>()

const student = useStudentStore()

type Phase = 'idle' | 'transcribing' | 'transcribed' | 'submitting' | 'done' | 'answered'
const phase = ref<Phase>('idle')
const busy = ref(false)
const fileRef = ref<HTMLInputElement | null>(null)
const previewUrl = ref('')
const errorText = ref('')
const questionText = ref('')
const steps = ref<string[]>([])
const confirmed = ref(false)
const result = ref<SubmissionResult | null>(null)
/** direct 模式下，诊断卡里展开原编辑器改步骤重交 */
const fixOpen = ref(false)
const captureId = ref<number | null>(null)
const answerText = ref('')
const savedCapture = ref(false)
const savingCapture = ref(false)

/** 转写卡片可见性：确认模式下转写后即显示；direct 模式仅在展开修改时显示 */
const cardVisible = computed(
  () =>
    (phase.value === 'transcribed' || phase.value === 'submitting' || phase.value === 'done') &&
    (!props.direct || fixOpen.value)
)

watch(phase, (p) => emit('active', p !== 'idle'))

/** v0.9.2：直达图库——父级按钮点击的当下调用，立刻打开系统文件/图库选择。
    取消选择不会触发 change，组件保持 idle 且不渲染任何可见内容。 */
function openPicker() {
  fileRef.value?.click()
}

/** 换图/重拍：清掉旧结果后同样直达选择器，不停在中间面板 */
function retake() {
  reset()
  openPicker()
}

defineExpose({ openPicker, processFile })

/** 只清「上一次批改产物」，供选新图时复用（reset 在此基础上再清转写与预览） */
function clearResult() {
  confirmed.value = false
  result.value = null
  captureId.value = null
  answerText.value = ''
  savedCapture.value = false
  fixOpen.value = false
}

function stepIcon(s: StepStatus): IconName {
  return { stem: 'file', ok: 'check', error: 'x', unparseable: 'help', skipped: 'minus' }[s] as IconName
}

function errDetail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  if (typeof d === 'string') return d
  return e instanceof Error ? e.message : ''
}

async function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  await processFile(file)
}

async function processFile(file: File) {
  errorText.value = ''
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    errorText.value = '这张图片格式不对，请上传 jpg / png / webp 格式的作答照片。'
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    errorText.value = '图片太大了（超过 10MB），请压缩后再试。'
    return
  }
  clearResult()
  previewUrl.value = URL.createObjectURL(file)
  phase.value = 'transcribing'
  busy.value = true
  try {
    const res = await student.reviewPhoto(file, props.questionId, props.questionStem || '')
    questionText.value = res.question_text
    steps.value = [...res.steps]
    if (res.mode === 'answer') {
      captureId.value = res.capture_id
      phase.value = 'answered'
      answerText.value = ''
      await student.agentChatStream(
        `学生上传的是只有题目、没有作答的图片。请先回答题目并讲清思路，不要判断学生做错，也不要创建错题记录。\n识别出的题目：${res.question_text.slice(0, 1600)}`,
        student.activeSessionId,
        (character) => { answerText.value += character }
      )
      phase.value = 'answered'
      return
    }
    if (res.mode === 'diagnosis' && res.diagnosis) {
      result.value = res.diagnosis
      confirmed.value = true
      phase.value = 'done'
      emit('graded', res.diagnosis)
      return
    }
    phase.value = 'transcribed'
    // direct 模式（v0.6.0）：转写完立刻提交诊断，不停在确认步
    if (props.direct) {
      busy.value = false
      await submitGrade()
      return
    }
  } catch (err) {
    if (captureId.value) {
      phase.value = 'answered'
      answerText.value = ''
      errorText.value = '题目已识别，但模型暂时无法生成讲解：' + (errDetail(err) || '请稍后重试。')
    } else {
      phase.value = 'idle'
      errorText.value = '识别失败：' + (errDetail(err) || '请稍后重试。')
    }
    console.error(err)
  } finally {
    busy.value = false
  }
}

async function saveCapture() {
  if (!captureId.value || savedCapture.value || savingCapture.value) return
  savingCapture.value = true
  try {
    await student.savePhotoCapture(captureId.value, answerText.value)
    savedCapture.value = true
  } catch (err) {
    errorText.value = '加入错题本失败：' + (errDetail(err) || '请稍后重试。')
  } finally {
    savingCapture.value = false
  }
}

async function submitGrade() {
  const cleaned = steps.value.map((s) => s.trim()).filter(Boolean)
  if (!cleaned.length) {
    errorText.value = '识别到的步骤是空的，展开修改补上步骤再重新提交。'
    phase.value = 'transcribed'
    if (props.direct) fixOpen.value = true
    return
  }
  errorText.value = ''
  phase.value = 'submitting'
  try {
    const res = await student.submitMath({ question_id: props.questionId, steps: cleaned })
    result.value = res
    confirmed.value = true
    fixOpen.value = false
    phase.value = 'done'
    emit('graded', res)
  } catch (e) {
    // 已有诊断结果时（改后重交失败）留在 done 展示旧结果；首次失败回转写卡
    phase.value = result.value ? 'done' : 'transcribed'
    errorText.value = '批改失败：' + (errDetail(e) || '请稍后重试。')
    console.error(e)
  }
}

async function confirm() {
  await submitGrade()
}

function reset() {
  phase.value = 'idle'
  previewUrl.value = ''
  questionText.value = ''
  steps.value = []
  clearResult()
  savingCapture.value = false
  errorText.value = ''
}
</script>

<style scoped>
.pgf { margin-top: 12px; }
.pgf-preview { max-width: 300px; max-height: 340px; border-radius: 10px; border: 1px solid var(--border); display: block; margin-bottom: 10px; }
.pgf-answer-question { color: var(--text-2); font-weight: 600; white-space: pre-wrap; }
.pgf-answer-copy { color: var(--text); line-height: 1.7; white-space: pre-wrap; }
.pgf-auto-booked { margin: 0 0 10px; color: var(--green); font-size: 12px; font-weight: 600; }
.pgf-status { display: inline-flex; align-items: center; gap: 7px; font-size: 14px; color: var(--text-2); padding: 8px 0; }
/* 待老师审核状态盒（v0.9.0，与对话页诊断卡同一套语义） */
.review-pending-box { display: flex; gap: 11px; align-items: flex-start; background: var(--amber-bg); border: 1px solid #FDE68A; border-radius: 10px; padding: 13px 15px; }
.review-pending-icon { width: 30px; height: 30px; border-radius: 50%; flex-shrink: 0; background: #fff; color: var(--amber); display: flex; align-items: center; justify-content: center; }
.review-pending-title { font-size: 14.5px; font-weight: 700; color: #92400E; }
.review-pending-sub { font-size: 13px; color: #92400E; opacity: 0.85; margin-top: 2px; }
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
.fix-box {
  margin-top: 14px; padding-top: 12px; border-top: 1px dashed #E4E9F2;
}
.fix-title { font-size: 13px; font-weight: 600; color: var(--text-2); margin-bottom: 6px; }
.fix-steps {
  margin: 0 0 10px; padding-left: 22px;
  font-size: 13.5px; color: var(--text-2); line-height: 1.7;
}
.spin { animation: pgf-spin 1s linear infinite; }
@keyframes pgf-spin { to { transform: rotate(360deg); } }
</style>
