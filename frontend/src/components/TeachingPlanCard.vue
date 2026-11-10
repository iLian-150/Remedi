<template>
  <section class="card teaching-plan" aria-labelledby="teaching-plan-title">
    <h3 id="teaching-plan-title"><AppIcon name="lightbulb" :size="18" /> 明天讲什么</h3>
    <p v-if="loading" class="loading" role="status">正在读取讲评重点…</p>
    <div v-else-if="loadError" class="plan-load-error">
      <span class="error-msg" role="alert">{{ loadError }}</span>
      <button type="button" class="btn secondary" @click="load">重试</button>
    </div>
    <template v-else>
      <ol v-if="plan.topics.length" class="topic-list">
        <li v-for="topic in plan.topics" :key="keyOf(topic)" class="topic-item">
          <div class="topic-summary">
            <div class="topic-main">
              <div class="topic-title">
                <span class="badge badge-gray">{{ subjectLabel(topic.subject) }}</span>
                <strong>{{ topic.knowledge_point }}</strong>
              </div>
              <p class="topic-metrics tnum">错误率 {{ Math.round(topic.error_rate * 100) }}% · {{ topic.student_count }} 名学生出错</p>
            </div>
            <div class="topic-actions">
              <button type="button" class="btn" :disabled="stateOf(topic).generating" @click="generate(topic)">
                {{ stateOf(topic).generating ? '生成中…' : stateOf(topic).exercise ? '重新生成变式练习' : '生成变式练习' }}
              </button>
              <button type="button" class="btn secondary" :disabled="marking !== ''" @click="markTaught(topic)">
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
      <p class="follow-up" role="status" aria-live="polite">
        <strong>回马枪：</strong>
        <template v-if="plan.follow_up">
          上次讲的{{ subjectLabel(plan.follow_up.subject) }}「{{ plan.follow_up.knowledge_point }}」，
          <template v-if="plan.follow_up.student_count">本周仍有 <b class="tnum">{{ plan.follow_up.student_count }}</b> 名学生出错。</template>
          <template v-else>本周暂无新的出错记录。</template>
        </template>
        <template v-else>暂无已讲记录。</template>
      </p>
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
.teaching-plan { margin-bottom: 16px; }
.topic-list { list-style: none; padding: 0; margin: 0; }
.topic-item { padding: 16px 0; border-bottom: 1px solid var(--border); }
.topic-summary, .topic-title, .topic-actions, .plan-load-error { display: flex; align-items: center; gap: 10px; }
.topic-summary { justify-content: space-between; flex-wrap: wrap; }
.topic-main { flex: 1; min-width: min(100%, 240px); }
.topic-title { align-items: baseline; overflow-wrap: anywhere; }
.topic-title .badge { flex-shrink: 0; }
.topic-metrics { font-size: 13px; color: var(--text-2); margin: 5px 0 0; }
.topic-actions { flex-wrap: wrap; }
.topic-actions .btn { font-size: 13px; padding: 7px 12px; }
.follow-up { color: var(--text-2); font-size: 13px; margin: 14px 0 0; }
.follow-up strong, .follow-up b { color: var(--text); }
.topic-exercise { margin-top: 14px; padding: 14px; background: var(--bg); border-radius: var(--radius-control); }
.exercise-prompt, .exercise-steps li, .exercise-answer { white-space: pre-wrap; overflow-wrap: anywhere; }
.topic-exercise summary { cursor: pointer; color: var(--primary); font-size: 13px; margin-top: 12px; }
.exercise-steps { padding-left: 22px; margin-top: 10px; }
.exercise-answer { margin-top: 10px; }
.plan-load-error { justify-content: space-between; }
</style>
