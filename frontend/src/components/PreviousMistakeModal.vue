<template>
  <div v-if="mistake" class="mistake-overlay" role="presentation" @click.self="emit('close')">
    <section class="mistake-modal" role="dialog" aria-modal="true" aria-label="历史同类错题">
      <header class="mistake-header">
        <div class="mistake-brand"><span>知</span><strong>Remedi</strong><small>原题与解题过程</small></div>
        <button type="button" class="mistake-close" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <div class="mistake-meta">
        <strong>{{ mistake.assignment_title }}</strong>
        <span>{{ mistake.knowledge_point }} · {{ formatDate(mistake.created_at) }}</span>
        <span v-if="mistake.review_status === 'pending'" class="badge badge-amber">老师复核中</span>
      </div>

      <div class="mistake-columns">
        <section class="mistake-panel">
          <h3>之前做错的题目</h3>
          <p class="mistake-question">{{ mistake.question_stem }}</p>
          <div v-if="submissionLoading" class="mistake-state">正在加载当时的作答…</div>
          <div v-else-if="submissionError" class="mistake-state error">{{ submissionError }}</div>
          <div v-else-if="submission" class="mistake-work">
            <h4>当时的作答</h4>
            <ol v-if="submission.steps.length">
              <li v-for="step in submission.steps" :key="step.seq" :class="{ wrong: step.seq === mistake.step_seq }">
                <span>{{ step.text }}</span>
                <b v-if="step.seq === mistake.step_seq">当时出错</b>
              </li>
            </ol>
            <p v-else class="mistake-state">没有保存可展示的作答步骤。</p>
          </div>
          <p v-else-if="mistake.step_text" class="mistake-old-step">当时的错误步骤：{{ mistake.step_text }}</p>
        </section>

        <section class="mistake-panel">
          <h3>解题过程与订正记录</h3>
          <div class="mistake-error-card">
            <div class="mistake-error-title"><span>错因</span><strong>{{ mistake.error_type }}</strong></div>
            <p>{{ mistake.detail || '系统记录了这一步的错误。' }}</p>
            <div v-if="mistake.step_seq" class="mistake-step-ref">第 {{ mistake.step_seq }} 步<template v-if="mistake.step_text">：{{ mistake.step_text }}</template></div>
          </div>
          <div v-if="mistake.solution_steps.length" class="mistake-solution">
            <h4>参考解题过程</h4>
            <ol>
              <li v-for="(step, index) in mistake.solution_steps" :key="index">{{ step }}</li>
            </ol>
          </div>
          <div v-if="submission?.steps.length" class="mistake-solution">
            <h4>当时的诊断步骤</h4>
            <ol>
              <li v-for="step in submission.steps" :key="step.seq" :class="{ wrong: step.seq === mistake.step_seq }">
                <span>{{ step.text }}</span>
                <b>{{ stepStatusLabel(step.status) }}</b>
              </li>
            </ol>
          </div>
          <div v-if="mistake.latest_correction" class="mistake-correction">
            <h4>最近一次订正</h4>
            <p>{{ mistake.latest_correction.content }}</p>
            <small>{{ mistake.latest_correction.is_correct ? '订正正确' : '订正记录' }} · {{ formatDate(mistake.latest_correction.submitted_at) }}</small>
            <p v-if="mistake.latest_correction.note" class="correction-note">{{ mistake.latest_correction.note }}</p>
          </div>
          <p v-else class="mistake-state">还没有订正记录。</p>
        </section>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import type { RelatedMistake, SubmissionResult } from '../api/types'
import { useStudentStore } from '../stores/student'
import { STEP_STATUS_TEXT } from '../api/types'

const props = defineProps<{ mistake: RelatedMistake | null }>()
const emit = defineEmits<{ close: [] }>()
const student = useStudentStore()
const submission = ref<SubmissionResult | null>(null)
const submissionLoading = ref(false)
const submissionError = ref('')
let requestSeq = 0

watch(() => props.mistake?.submission_id, async (submissionId) => {
  const seq = ++requestSeq
  submission.value = null
  submissionError.value = ''
  if (!submissionId) {
    submissionLoading.value = false
    return
  }
  submissionLoading.value = true
  try {
    const result = await student.fetchSubmissionDetail(submissionId)
    if (seq === requestSeq) submission.value = result
  } catch {
    if (seq === requestSeq) submissionError.value = '作答过程暂时无法加载，请稍后重试。'
  } finally {
    if (seq === requestSeq) submissionLoading.value = false
  }
}, { immediate: true })

function formatDate(value: string) {
  return new Date(value).toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

function stepStatusLabel(status: string) {
  return STEP_STATUS_TEXT[status as keyof typeof STEP_STATUS_TEXT] ?? status
}
</script>

<style scoped>
.mistake-overlay { position: fixed; inset: 0; z-index: 500; display: flex; align-items: center; justify-content: center; padding: 24px; background: rgba(20, 31, 29, .68); }
.mistake-modal { width: min(1500px, 96vw); max-height: min(88vh, 980px); display: flex; flex-direction: column; overflow: hidden; border-radius: 18px; background: #f7faf7; box-shadow: 0 24px 80px rgba(0, 0, 0, .24); }
.mistake-header { flex: none; display: flex; justify-content: space-between; align-items: center; padding: 15px 24px; border-bottom: 1px solid #e5ece6; background: #fff; }
.mistake-brand { display: flex; align-items: center; gap: 10px; color: #263b36; }
.mistake-brand span { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 10px; color: white; background: #202a29; font-weight: 700; }
.mistake-brand strong { font-size: 17px; }
.mistake-brand small { margin-left: 5px; color: #85928d; }
.mistake-close { width: 38px; height: 38px; border: 1px solid #e4ebe5; border-radius: 50%; background: white; color: #65736d; font-size: 25px; cursor: pointer; }
.mistake-meta { flex: none; display: flex; justify-content: space-between; gap: 12px; padding: 12px 24px; color: #53635d; background: #eef5ef; font-size: 13px; }
.mistake-meta span { color: #7b8983; }
.mistake-meta .badge-amber { color: #92400e; }
.mistake-columns { min-height: 0; overflow: auto; display: grid; grid-template-columns: 1fr 1.15fr; gap: 14px; padding: 14px; }
.mistake-panel { min-width: 0; padding: 18px; border: 1px solid #e5ece6; border-radius: 15px; background: white; }
.mistake-panel h3 { margin: 0 0 14px; color: #30443d; font-size: 18px; }
.mistake-question { white-space: pre-wrap; margin: 0; padding: 16px; border-radius: 10px; background: #f8faf8; color: #44534d; line-height: 1.8; }
.mistake-work, .mistake-solution, .mistake-correction { margin-top: 20px; }
.mistake-work h4, .mistake-solution h4, .mistake-correction h4 { margin: 0 0 9px; color: #45554e; font-size: 14px; }
.mistake-work ol, .mistake-solution ol { margin: 0; padding-left: 24px; color: #53635d; line-height: 1.8; }
.mistake-work li, .mistake-solution li { padding: 6px 8px; border-bottom: 1px solid #eff2ef; }
.mistake-work li.wrong, .mistake-solution li.wrong { border-radius: 7px; background: #fff4ef; color: #a94d3f; }
.mistake-work li b, .mistake-solution li b { display: block; margin-top: 3px; color: #b65545; font-size: 12px; font-weight: 600; }
.mistake-error-card { padding: 14px 16px; border: 1px solid #c9dfcc; border-radius: 11px; background: #f4faf5; color: #52635b; line-height: 1.7; }
.mistake-error-title { display: flex; gap: 10px; align-items: center; margin-bottom: 5px; color: #73837b; font-size: 13px; }
.mistake-error-title strong { color: #416f53; }
.mistake-error-card p { margin: 0; white-space: pre-wrap; }
.mistake-step-ref, .mistake-old-step { margin-top: 10px; color: #73837b; font-size: 13px; }
.mistake-correction { padding: 14px 16px; border-radius: 10px; background: #f8faf8; }
.mistake-correction p { margin: 0 0 7px; white-space: pre-wrap; color: #53635d; line-height: 1.7; }
.mistake-correction small { color: #829089; }
.mistake-correction .correction-note { margin-top: 8px; }
.mistake-state { margin: 15px 0 0; color: #89958f; font-size: 13px; }
.mistake-state.error { color: #b65545; }
@media (max-width: 760px) { .mistake-overlay { padding: 10px; } .mistake-modal { width: 100%; max-height: 94vh; } .mistake-columns { grid-template-columns: 1fr; padding: 9px; } .mistake-panel { padding: 14px; } .mistake-meta { align-items: flex-start; flex-direction: column; } }
</style>
