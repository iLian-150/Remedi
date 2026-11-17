<template>
  <section class="card teaching-plan" aria-labelledby="teaching-plan-title">
    <h2 id="teaching-plan-title"><AppIcon name="lightbulb" :size="18" /> 讲评重点</h2>
    <p v-if="loading" class="loading" role="status">正在读取讲评重点…</p>
    <div v-else-if="loadError" class="plan-load-error">
      <span class="error-msg" role="alert">{{ loadError }}</span>
      <button type="button" class="btn secondary small" @click="load">重试</button>
    </div>
    <template v-else>
      <ol v-if="plan.topics.length" class="topic-list">
        <li v-for="topic in plan.topics" :key="keyOf(topic)" class="topic-item">
          <div class="topic-summary">
            <div class="topic-main">
              <strong>{{ topic.knowledge_point }}</strong>
              <p class="topic-metrics tnum">
                {{ subjectLabel(topic.subject) }} · {{ topic.student_count }} 人出错 · 错误率 {{ Math.round(topic.error_rate * 100) }}%
              </p>
            </div>
            <div class="topic-actions">
              <button type="button" class="btn secondary small" :disabled="stateOf(topic).generating" @click="generate(topic)">
                {{ stateOf(topic).generating ? '生成中…' : stateOf(topic).exercise ? '重新生成变式练习' : '生成变式练习' }}
              </button>
              <button type="button" class="btn ghost small" :disabled="marking !== ''" @click="markTaught(topic)">
                {{ marking === keyOf(topic) ? '记录中…' : topic.taught_at ? '再次标记已讲' : '标记已讲' }}
              </button>
            </div>
          </div>
          <p v-if="stateOf(topic).error" class="error-msg" role="alert">{{ stateOf(topic).error }}</p>
          <section v-if="stateOf(topic).exercise" class="topic-exercise" :aria-label="`${topic.knowledge_point}变式练习`">
            <p class="exercise-prompt">{{ stateOf(topic).exercise!.prompt }}</p>
            <details>
              <summary>参考解法与答案</summary>
              <ol class="exercise-steps">
                <li v-for="(step, i) in stateOf(topic).exercise!.standard_steps" :key="i">{{ step }}</li>
              </ol>
              <p class="exercise-answer">{{ stateOf(topic).exercise!.answer }}</p>
            </details>
          </section>
        </li>
      </ol>
      <p v-else class="empty">暂无涉及多名学生的共性薄弱点。</p>
      <div role="status" aria-live="polite">
        <div v-if="plan.follow_up" class="follow-up">
          <strong>讲后跟进</strong>
          <p>{{ subjectLabel(plan.follow_up.subject) }} · {{ plan.follow_up.knowledge_point }}</p>
          <p v-if="plan.follow_up.student_count">本周讲解后仍有 <b class="tnum">{{ plan.follow_up.student_count }}</b> 人出错</p>
          <p v-else>本周讲解后暂无新的出错记录</p>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { isAxiosError } from 'axios'
import type { TeachingExercise, TeachingPlan, TeachingTopic } from '../api/types'
import { useTeacherStore } from '../stores/teacher'
import { getSubjectLabel } from '../utils/subjectLabels'
import AppIcon from './icons/AppIcon.vue'

const teacher = useTeacherStore()
const plan = ref<TeachingPlan>({ topics: [], follow_up: null })
const loading = ref(false)
const loadError = ref('')
const marking = ref('')
const controller = new AbortController()
const states = reactive<Record<string, { generating: boolean; error: string; exercise: TeachingExercise | null }>>({})
const subjectLabel = (subject: string) => getSubjectLabel(subject, subject)
const keyOf = (topic: TeachingTopic) => `${topic.subject}:${topic.knowledge_point}`
function stateOf(topic: TeachingTopic) {
  return states[keyOf(topic)] ??= { generating: false, error: '', exercise: null }
}
function errorMessage(error: unknown, fallback: string): string {
  return isAxiosError(error) && typeof error.response?.data?.detail === 'string'
    ? error.response.data.detail : fallback
}
async function load() {
  loading.value = true
  loadError.value = ''
  try {
    plan.value = await teacher.fetchTeachingPlan(controller.signal)
  } catch (error) {
    if (!controller.signal.aborted) loadError.value = errorMessage(error, '讲评重点加载失败，请重试。')
  } finally {
    loading.value = false
  }
}
async function generate(topic: TeachingTopic) {
  const state = stateOf(topic)
  if (state.generating) return
  state.generating = true
  state.error = ''
  try {
    state.exercise = await teacher.generateTeachingExercise(topic.subject, topic.knowledge_point, controller.signal)
  } catch (error) {
    if (!controller.signal.aborted) state.error = errorMessage(error, '变式练习生成失败，请重试。')
  } finally {
    state.generating = false
  }
}
async function markTaught(topic: TeachingTopic) {
  if (marking.value) return
  const state = stateOf(topic)
  state.error = ''
  marking.value = keyOf(topic)
  try {
    plan.value = await teacher.markTopicTaught(topic.subject, topic.knowledge_point, controller.signal)
  } catch (error) {
    if (!controller.signal.aborted) state.error = errorMessage(error, '讲解记录保存失败，请重试。')
  } finally {
    marking.value = ''
  }
}
onMounted(load)
onBeforeUnmount(() => controller.abort())
</script>

<style scoped>
.teaching-plan { margin-bottom: 0; }
.teaching-plan h2 { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 16px; font-weight: 700; }
.teaching-plan h2 svg { color: var(--primary); }
.teaching-plan .empty, .teaching-plan .loading { padding-block: 16px; }
.topic-list { list-style: none; padding: 0; margin: 0; }
.topic-item { padding: 13px 0; }
.topic-item + .topic-item { border-top: 1px solid var(--border); }
.topic-summary, .topic-actions, .plan-load-error { display: flex; align-items: center; gap: 8px 10px; }
.topic-summary { justify-content: space-between; flex-wrap: wrap; }
.topic-main { flex: 1 1 min(100%, 210px); min-width: 0; overflow-wrap: anywhere; }
.topic-metrics { font-size: 13px; color: var(--text-2); margin: 4px 0 0; }
.topic-actions { flex-wrap: wrap; }
.follow-up {
  display: grid;
  gap: 3px;
  margin-top: 8px;
  padding: 12px 14px;
  border-radius: var(--radius-control);
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 13px;
  overflow-wrap: anywhere;
}
.follow-up strong, .follow-up b { color: var(--text); }
.topic-exercise { margin-top: 14px; padding: 14px; background: var(--bg); border-radius: var(--radius-control); }
.exercise-prompt, .exercise-steps li, .exercise-answer { white-space: pre-wrap; overflow-wrap: anywhere; }
.topic-exercise summary { cursor: pointer; color: var(--primary); font-size: 13px; margin-top: 12px; }
.exercise-steps { padding-left: 22px; margin-top: 10px; }
.exercise-answer { margin-top: 10px; }
.plan-load-error { flex-wrap: wrap; }
.plan-load-error .error-msg { margin: 0; }
</style>
