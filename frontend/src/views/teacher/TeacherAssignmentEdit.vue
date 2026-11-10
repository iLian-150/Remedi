<template>
  <div class="page assignment-edit">
    <div class="edit-heading">
      <router-link :to="`/teacher/assignments/${assignmentId}`" class="back-link"><AppIcon name="chevron-left" :size="16" /> 返回题目</router-link>
      <h2>编辑作业</h2>
    </div>
    <div v-if="loading" class="loading">作业加载中…</div>
    <div v-else-if="loadError" class="error-msg" role="alert">{{ loadError }}</div>
    <form v-else-if="form" @submit.prevent="save">
      <div class="card">
        <div class="form-row"><label for="edit-title">作业标题</label><input id="edit-title" v-model="form.title" maxlength="128" type="text" required /></div>
        <div class="form-row"><label for="edit-description">作业说明（选填）</label><textarea id="edit-description" v-model="form.description" maxlength="2000" rows="3"></textarea></div>
        <div class="form-row"><label for="edit-total">作业总分</label><input id="edit-total" v-model.number="form.total_score" type="number" min="0.01" max="10000" step="any" :disabled="form.content_locked" required /></div>
        <div class="form-row"><label for="edit-deadline">截止时间（选填）</label><input id="edit-deadline" v-model="form.deadline" type="datetime-local" step="1" :disabled="form.content_locked" /></div>
        <div v-if="form.mode === 'offline'" class="form-row"><label for="edit-page-range">练习册范围（选填）</label><input id="edit-page-range" v-model="form.page_range" type="text" maxlength="64" :disabled="form.content_locked" /></div>
        <label class="revision-option"><input v-model="form.allow_revision" type="checkbox" :disabled="form.content_locked" /> 允许学生在截止前修改已提交的作答</label>
      </div>
      <fieldset :disabled="form.content_locked || saving" class="card class-fields">
        <legend>接收班级</legend>
        <p v-if="!form.class_ids.length" class="hint">当前作业未限定班级。</p>
        <div class="class-options">
          <label v-for="room in form.class_options" :key="room.id" class="class-option"><input v-model="form.class_ids" type="checkbox" :value="room.id" /> {{ room.name }}</label>
        </div>
      </fieldset>
      <p v-if="form.content_locked" class="lock-notice" role="status">已有学生作答，题目、分值、班级和提交设置不可修改；可修改作业标题和说明。</p>
      <p v-else-if="form.groups.length" class="hint diagram-note">修改大题材料或小题题干后，已有图形会自动重新生成。</p>
      <fieldset :disabled="form.content_locked || saving" class="question-fields">
        <div class="card">
          <template v-for="(question, index) in form.questions" :key="question.id">
            <div v-if="showGroup(question, index) && groupFor(question)" class="group-edit">
              <div class="form-row">
                <label :for="`group-${question.group_id}`">大题材料</label>
                <textarea :id="`group-${question.group_id}`" v-model="groupFor(question)!.stem" maxlength="4000" rows="3" required></textarea>
              </div>
            </div>
            <section class="question-edit">
              <h3>第 {{ index + 1 }} 题</h3>
              <div class="form-row"><label :for="`prompt-${question.id}`">题干</label><textarea :id="`prompt-${question.id}`" v-model="question.prompt" maxlength="2000" rows="3" required></textarea></div>
              <div class="question-meta">
                <div class="form-row"><label :for="`knowledge-${question.id}`">知识点（选填）</label><input :id="`knowledge-${question.id}`" v-model="question.knowledge_point" type="text" maxlength="64" /></div>
                <div class="form-row"><label :for="`weight-${question.id}`">分值占比（%）</label><input :id="`weight-${question.id}`" v-model.number="question.weight_pct" type="number" min="0" max="100" step="any" required /></div>
              </div>
              <div class="form-row"><label :for="`answer-${question.id}`">参考答案 / 标准步骤（选填）</label><textarea :id="`answer-${question.id}`" v-model="question.standard_answer" rows="3"></textarea></div>
            </section>
          </template>
        </div>
      </fieldset>
      <div v-if="saveError" class="error-msg" role="alert">{{ saveError }}</div>
      <div class="toolbar edit-actions">
        <span v-if="!form.content_locked" class="hint">分值占比合计 {{ weightSum.toFixed(1) }}%</span>
        <router-link :to="`/teacher/assignments/${assignmentId}`" class="btn secondary">取消</router-link>
        <button class="btn" type="submit" :disabled="saving">{{ saving ? '保存中…' : '保存修改' }}</button>
      </div>
    </form>
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import api from '../../api/client'
import AppIcon from '../../components/icons/AppIcon.vue'

interface EditQuestion { id: number; subject: string; prompt: string; knowledge_point: string; standard_answer: string | null; group_id: number | null; weight_pct: number }
interface EditGroup { id: number; stem: string }
interface EditForm { id: number; title: string; description: string | null; total_score: number; deadline: string | null; mode: string; page_range: string | null; allow_revision: boolean; class_ids: number[]; class_options: { id: number; name: string }[]; questions: EditQuestion[]; groups: EditGroup[]; revision: string; content_locked: boolean }
const route = useRoute()
const router = useRouter()
const assignmentId = computed(() => Number(route.params.id))
const form = ref<EditForm | null>(null)
const loading = ref(true)
const loadError = ref('')
const saveError = ref('')
const saving = ref(false)
let initialState = ''
let loadGeneration = 0
let saved = false
const weightSum = computed(() => form.value?.questions.reduce((sum, q) => sum + Number(q.weight_pct || 0), 0) ?? 0)
const groupsById = computed(() => new Map((form.value?.groups ?? []).map((group) => [group.id, group])))
function groupFor(question: EditQuestion) { return question.group_id ? groupsById.value.get(question.group_id) : undefined }
function showGroup(question: EditQuestion, index: number) { return !!question.group_id && form.value?.questions[index - 1]?.group_id !== question.group_id }
async function load(id: number) {
  const generation = ++loadGeneration
  loading.value = true
  loadError.value = ''
  try {
    const { data } = await api.get<EditForm>(`/api/teacher/assignments/${id}/edit`)
    if (generation !== loadGeneration) return
    form.value = data
    initialState = JSON.stringify(data)
    saved = false
  } catch (error: unknown) {
    if (generation !== loadGeneration) return
    const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
    loadError.value = typeof detail === 'string' ? detail : '作业加载失败，请稍后重试。'
  } finally { if (generation === loadGeneration) loading.value = false }
}
watch(assignmentId, (id) => {
  if (!Number.isSafeInteger(id) || id <= 0) { loading.value = false; loadError.value = '作业不存在。'; return }
  void load(id)
}, { immediate: true })
onBeforeUnmount(() => { loadGeneration++ })
onBeforeRouteLeave(() => {
  if (!saved && form.value && JSON.stringify(form.value) !== initialState && !window.confirm('修改尚未保存，确定离开吗？')) return false
})
async function save() {
  if (!form.value || saving.value) return
  const current = form.value
  saveError.value = ''
  if (!current.title.trim() || current.questions.some((q) => !q.prompt.trim()) || current.groups.some((g) => !g.stem.trim())) { saveError.value = '请填写作业标题和全部题干。'; return }
  if (!current.content_locked && (!Number.isFinite(current.total_score) || current.total_score <= 0 || current.total_score > 10000 || current.questions.some((q) => !Number.isFinite(q.weight_pct) || q.weight_pct < 0 || q.weight_pct > 100) || Math.abs(weightSum.value - 100) > 0.5)) { saveError.value = '请检查作业总分和分值占比，占比合计应为 100%。'; return }
  saving.value = true
  try {
    await api.put(`/api/teacher/assignments/${assignmentId.value}`, {
      revision: current.revision, title: current.title, description: current.description,
      total_score: current.total_score, deadline: current.deadline || null,
      page_range: current.page_range || null, allow_revision: current.allow_revision, class_ids: current.class_ids,
      questions: current.questions.map(({ id, prompt, knowledge_point, standard_answer, weight_pct }) => ({ id, prompt, knowledge_point, standard_answer, weight_pct })),
      groups: current.groups.map(({ id, stem }) => ({ id, stem })),
    })
    saved = true
    await router.push(`/teacher/assignments/${assignmentId.value}`)
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
    saveError.value = typeof detail === 'string' ? detail : '保存失败，请稍后重试。'
  } finally { saving.value = false }
}
</script>
<style scoped>
.edit-heading { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }
.edit-heading h2 { margin: 0; }
.assignment-edit input[type="number"], .assignment-edit input[type="datetime-local"] { width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-control); font: inherit; color: var(--text); background: var(--card); }
.assignment-edit input:disabled, .assignment-edit textarea:disabled { color: var(--text-2); background: var(--gray-bg); }
.revision-option { display: flex; align-items: center; gap: 8px; color: var(--text); }
.class-fields { min-width: 0; }
.class-fields legend { font-weight: 600; padding: 0 4px; }
.class-options { display: flex; flex-wrap: wrap; gap: 12px; }
.class-option { display: flex; gap: 8px; align-items: center; padding: 8px 12px; border: 1px solid var(--border); border-radius: var(--radius-control); }
.question-fields { border: 0; min-width: 0; padding: 0; margin: 0; }
.question-edit { padding: 16px 0; border-bottom: 1px solid var(--border); }
.question-edit:last-child { border-bottom: 0; }
.question-edit h3 { margin-bottom: 12px; font-size: 16px; }
.question-meta { display: grid; grid-template-columns: minmax(0, 1fr) minmax(150px, .35fr); gap: 16px; }
.group-edit { padding: 16px; border-radius: var(--radius-control); background: var(--primary-50); }
.group-edit .form-row { margin: 0; }
.lock-notice { padding: 12px 16px; margin-bottom: 16px; border-radius: var(--radius-control); background: var(--amber-bg); color: var(--amber); }
.diagram-note { margin: 0 0 12px; }
.edit-actions { justify-content: flex-end; gap: 12px; }
@media (max-width: 760px) { .question-meta { grid-template-columns: minmax(0, 1fr); gap: 0; } }
</style>
