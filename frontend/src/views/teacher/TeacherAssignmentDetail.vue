<template>
  <div class="page">
    <div class="detail-heading">
      <router-link to="/teacher/assignments/manage" class="back-link"><AppIcon name="chevron-left" :size="16" /> 返回作业管理</router-link>
      <h2>作业题目</h2>
      <router-link v-if="detail?.can_delete" :to="`/teacher/assignments/${detail.id}/edit`" class="btn small secondary inline-icon"><AppIcon name="edit" :size="15" /> 编辑作业</router-link>
    </div>

    <div v-if="loading" class="loading">作业加载中…</div>
    <div v-else-if="error" class="error-msg" role="alert">{{ error }}</div>
    <template v-else-if="detail">
      <div class="card detail-info">
        <h3>{{ detail.title }}</h3>
        <p class="hint">共 {{ detail.questions.length }} 题 · 满分 {{ detail.total_score }} 分</p>
        <p v-if="detail.description" class="detail-text">{{ detail.description }}</p>
      </div>
      <div class="card questions-card">
        <template v-for="(question, index) in detail.questions" :key="question.id">
          <section v-if="showGroup(question, index) && groupFor(question)" class="group-material">
            <h3>大题材料</h3>
            <div class="group-content" :class="{ 'has-figure': groupFor(question)?.diagram }">
              <p class="detail-text">{{ groupFor(question)?.stem }}</p>
              <FigureRenderer v-if="groupFor(question)?.diagram" :figure="groupFor(question)!.diagram!" />
              <p v-else-if="groupFor(question)?.diagram_status === 'queued' || groupFor(question)?.diagram_status === 'processing'" class="hint" role="status">图形生成中，将自动显示</p>
              <p v-else-if="groupFor(question)?.diagram_status === 'failed'" class="hint" role="status">图形生成失败，可返回作业管理重试</p>
            </div>
          </section>
          <section class="question-item">
            <h3>第 {{ index + 1 }} 题</h3>
            <p class="detail-text question-text">{{ question.prompt }}</p>
            <p v-if="question.knowledge_point" class="hint">知识点：{{ question.knowledge_point }}</p>
            <div v-if="question.standard_answer" class="answer-block">
              <span class="hint">参考答案 / 标准步骤</span>
              <p class="detail-text">{{ question.standard_answer }}</p>
            </div>
          </section>
        </template>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import api from '../../api/client'
import type { TeacherAssignmentDetail, TeacherAssignmentQuestion } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'
import FigureRenderer from '../../components/FigureRenderer.vue'

const route = useRoute()
const detail = ref<TeacherAssignmentDetail | null>(null)
const loading = ref(true)
const error = ref('')
const groupsById = computed(() => new Map((detail.value?.groups ?? []).map((group) => [group.id, group])))
let requestGeneration = 0
let pollHandle: number | null = null

function groupFor(question: TeacherAssignmentQuestion) {
  return question.group_id ? groupsById.value.get(question.group_id) : undefined
}
function showGroup(question: TeacherAssignmentQuestion, index: number) {
  return !!question.group_id && detail.value?.questions[index - 1]?.group_id !== question.group_id
}
function clearPoll() {
  if (pollHandle !== null) window.clearTimeout(pollHandle)
  pollHandle = null
}
async function loadDetail(id: number, generation: number, background = false) {
  if (!background) { loading.value = true; error.value = ''; detail.value = null }
  try {
    const { data } = await api.get<TeacherAssignmentDetail>(`/api/teacher/assignments/${id}`)
    if (generation !== requestGeneration) return
    detail.value = data
    if (data.groups.some((group) => group.diagram_status === 'queued' || group.diagram_status === 'processing')) {
      pollHandle = window.setTimeout(() => { void loadDetail(id, generation, true) }, 4000)
    }
  } catch {
    if (generation !== requestGeneration) return
    if (background) pollHandle = window.setTimeout(() => { void loadDetail(id, generation, true) }, 4000)
    else error.value = '作业不存在或暂时无法加载，请返回重试。'
  } finally {
    if (generation === requestGeneration && !background) loading.value = false
  }
}
watch(() => route.params.id, (value) => {
  clearPoll()
  const generation = ++requestGeneration
  const id = Number(value)
  if (!Number.isSafeInteger(id) || id <= 0) { loading.value = false; detail.value = null; error.value = '作业不存在。'; return }
  void loadDetail(id, generation)
}, { immediate: true })
onBeforeUnmount(() => { requestGeneration++; clearPoll() })
</script>

<style scoped>
.detail-heading { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }
.detail-heading h2 { margin: 0; }
.detail-info h3 { margin-bottom: 6px; }
.detail-info .detail-text { margin-top: 12px; }
.detail-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.group-material { padding: 16px; background: var(--primary-50); border-radius: var(--radius-sm); }
.group-material h3, .question-item h3 { margin-bottom: 8px; font-size: 16px; }
.group-content.has-figure { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 18px; align-items: start; }
.group-content :deep(.question-figure) { margin-top: 0; }
.question-item { padding: 16px 0; border-bottom: 1px solid var(--border); }
.question-item:last-child { border-bottom: 0; padding-bottom: 0; }
.question-text { font-size: 16px; }
.question-item .hint { margin-top: 8px; }
.answer-block { margin-top: 12px; }
.answer-block .detail-text { margin-top: 4px; }
@media (max-width: 760px) { .group-content.has-figure { grid-template-columns: minmax(0, 1fr); gap: 8px; } }
</style>
