<template>
  <div class="mistake-map-view remedi-mistake-book">
    <main class="mistakes-panel" :class="`is-${view}`" aria-label="学生错题本">
      <div class="mistake-board-toolbar" role="toolbar" aria-label="错题本视图操作">
        <div class="mistake-view-switch" role="group" aria-label="切换错题本样式">
          <button v-for="item in viewOptions" :key="item.key" type="button" :class="{ selected: view === item.key }" :aria-pressed="view === item.key" @click="setView(item.key)"><AppIcon :name="item.icon" :size="15"/>{{ item.label }}</button>
        </div>
        <button class="mistake-board-refresh" type="button" :disabled="loading" aria-label="刷新错题本" title="刷新错题" @click="loadMistakes">↻</button>
      </div>

      <div v-if="removedAssignment" class="mistake-removal-notice" role="status">
        <span>已将「{{ removedAssignment.title }}」的整份错题移出，历史记录仍保留。<em v-if="actionError">{{ actionError }}</em></span>
        <button type="button" :disabled="workingKey === `restore:${removedAssignment.id}`" @click="restoreAssignment">{{ workingKey === `restore:${removedAssignment.id}` ? '恢复中…' : '撤销' }}</button>
        <button type="button" class="mistake-notice-close" aria-label="关闭移出提示" @click="removedAssignment = null">×</button>
      </div>
      <p v-if="loadError" class="notebook-action-error" role="alert">{{ loadError }}</p>

      <section v-if="view === 'notebook'" class="mistake-notebook" :class="{ 'is-split': Boolean(selectedMistake), 'is-reversed': assistantOnLeft, 'is-assistant-fullscreen': assistantFullscreen }" aria-label="按作业复习错题本" :aria-busy="loading">
        <div class="mistake-notebook-content">
          <header class="notebook-header">
            <div class="notebook-eyebrow"><AppIcon name="book" :size="17"/><span>温故 · 知新</span></div>
            <h1>我的错题本<span>。</span></h1>
            <p>按作业梳理错因，学完一整份作业，再一次性移出错题本。</p>
          </header>

          <div class="notebook-overview" aria-label="错题复习概览">
            <div class="notebook-stat total"><span class="notebook-stat-icon"><AppIcon name="clipboard" :size="18"/></span><div class="notebook-stat-copy"><span>收录错题</span><strong>{{ loading ? '—' : allMistakes.length }}<small>条</small></strong></div></div>
            <div class="notebook-stat pending"><span class="notebook-stat-icon"><AppIcon name="history" :size="18"/></span><div class="notebook-stat-copy"><span>待学习作业</span><strong>{{ loading ? '—' : pendingAssignments.length }}<small>份</small></strong></div></div>
            <div class="notebook-stat repaired"><span class="notebook-stat-icon"><AppIcon name="check" :size="18"/></span><div class="notebook-stat-copy"><span>错误类别</span><strong>{{ loading ? '—' : `${studiedCategoryCount}/${categoryCount}` }}</strong></div></div>
            <div class="notebook-progress"><label><span>错误类别学习进度</span><b>{{ loading ? '—' : `${studyPercent}%` }}</b></label><div class="notebook-progress-track" role="progressbar" aria-label="错误类别学习进度" :aria-valuenow="loading ? undefined : studyPercent" aria-valuemin="0" aria-valuemax="100"><span :style="{ width: `${loading ? 0 : studyPercent}%` }"/></div></div>
          </div>

          <div class="notebook-workspace">
            <div class="notebook-section-head"><div><h2>从一份作业开始</h2><p>同类错误会合并显示，也会提醒你以前在哪份作业错过。</p></div><button class="notebook-review-button" type="button" :disabled="loading || !nextMistake" @click="nextMistake && openAssistant(nextMistake)">开始复习<span aria-hidden="true">→</span></button></div>
            <div class="notebook-subjects" role="group" aria-label="按学科筛选">
              <button type="button" :class="{ selected: subject === 'all' }" :aria-pressed="subject === 'all'" @click="subject = 'all'">全部学科<small>{{ allMistakes.length }}</small></button>
              <button v-for="option in subjectOptions" :key="option.key" type="button" :class="{ selected: subject === option.key }" :aria-pressed="subject === option.key" @click="subject = option.key">{{ option.label }}<small>{{ allMistakes.filter((item) => item.question_subject === option.key).length }}</small></button>
            </div>
            <div class="notebook-filterbar">
              <div class="notebook-status-tabs" role="group" aria-label="按作业学习进度筛选">
                <button v-for="option in statusOptions" :key="option.key" type="button" :class="{ selected: status === option.key }" :aria-pressed="status === option.key" @click="status = option.key">{{ option.label }}<small>{{ option.count }}</small></button>
              </div>
              <div class="notebook-search-tools">
                <label class="notebook-search"><AppIcon name="file" :size="15"/><input v-model="query" type="search" placeholder="搜索作业、错因、知识点…" aria-label="搜索作业和错因"/><button v-if="query" type="button" aria-label="清空搜索" @click="query = ''">×</button></label>
                <label class="notebook-sort"><select v-model="sort" aria-label="作业排序"><option value="recent">最近作业</option><option value="oldest">最早作业</option><option value="priority">优先看重复错因</option></select></label>
              </div>
            </div>
            <div class="notebook-results-note" role="status" aria-live="polite"><span>{{ loading ? '正在整理你的错题…' : `共 ${visibleAssignments.length} 份${filtersApplied ? '符合条件的' : '待复习'}作业` }}</span><button v-if="filtersApplied" type="button" @click="resetFilters">重置筛选</button></div>
            <p v-if="actionError && !removedAssignment" class="notebook-action-error" role="alert">{{ actionError }}</p>
            <div v-if="loading" class="notebook-assignment-list notebook-loading" aria-hidden="true"><div v-for="index in 4" :key="index" class="notebook-skeleton"><span/><span/><span/></div></div>
            <div v-else-if="visibleAssignments.length" class="notebook-assignment-list">
              <details v-for="(assignment, index) in visibleAssignments" :key="assignment.id" class="notebook-assignment" :open="index === 0">
                <summary>
                  <span class="notebook-assignment-chevron" aria-hidden="true">⌄</span>
                  <span class="notebook-subject-badge"><AppIcon name="book" :size="14"/>{{ subjectName(assignment.subject) }}</span>
                  <span class="notebook-assignment-title"><strong>{{ assignment.title }}</strong><small>{{ formatDate(assignment.createdAt) }} · {{ assignmentSummary(assignment) }}</small></span>
                  <span class="notebook-assignment-progress">{{ assignment.items.every(isStudentSaved) ? '自主收录' : `${assignment.categories.filter((item) => item.studied).length}/${assignment.categories.length} 类` }}</span>
                  <span class="notebook-assignment-state" :class="{ ready: assignment.ready }">{{ assignment.items.every(isStudentSaved) ? '已收录' : assignment.ready ? '已学完' : '待学习' }}</span>
                </summary>
                <div class="notebook-assignment-content">
                  <section v-for="category in assignment.categories" :key="category.key" class="notebook-category" :class="{ studied: category.studied }">
                    <header class="notebook-category-head"><div><span class="notebook-category-dot"/><div><h4>{{ category.label }}</h4><small>{{ category.items.length }} 条记录</small></div></div><button v-if="!category.items.every(isStudentSaved)" type="button" :class="{ studied: category.studied }" :disabled="workingKey === studyKey(assignment.id, category.key)" @click="toggleCategory(assignment, category)">{{ workingKey === studyKey(assignment.id, category.key) ? '保存中…' : category.studied ? '已学会 · 撤销' : '标记已学会' }}</button></header>
                    <div v-if="category.similar.length" class="notebook-repeat-note"><strong>同类问题再次出现</strong><span>你之前也在这些作业中错过类似题目：</span><div><button v-for="previous in category.similar" :key="previous.id" type="button" @click="openDiagnosis(previous.submission_id)">{{ previous.assignment_title }} · {{ formatDate(previous.assignment_created_at) }} · 回看错题</button></div></div>
                    <div class="notebook-category-questions"><article v-for="mistake in category.items" :key="mistake.id">
                      <button type="button" class="notebook-question-open" :class="{ active: selectedMistake?.id === mistake.id }" @click="openAssistant(mistake)"><strong>{{ isStudentSaved(mistake) ? '自主收录题目' : `第 ${mistake.question_order} 题${mistake.step_seq ? ` · 第 ${mistake.step_seq} 步` : ''}` }}</strong><small>{{ mistake.knowledge_point }} · {{ mistake.error_type }}</small><span class="notebook-question-excerpt">{{ mistake.question_stem }}</span><span class="notebook-question-detail">{{ safe(mistake.detail || '') }}</span></button>
                      <button v-if="!isStudentSaved(mistake)" type="button" @click="openDiagnosis(mistake.submission_id)">查看原题<span aria-hidden="true">→</span></button>
                      <button v-else type="button" :disabled="workingKey === `archive:${mistake.assignment_id}`" @click="archiveSaved(mistake)">{{ workingKey === `archive:${mistake.assignment_id}` ? '正在移出…' : '移出错题本' }}</button>
                    </article></div>
                  </section>
                  <footer v-if="!assignment.items.every(isStudentSaved)" class="notebook-assignment-footer"><span>{{ assignment.ready ? '这份作业的错误类别都已学完。' : `还需学完 ${assignment.categories.filter((item) => !item.studied).length} 类，才能移出整份作业。` }}</span><button type="button" :disabled="!assignment.ready || workingKey === `archive:${assignment.id}`" @click="archiveAssignment(assignment)">{{ workingKey === `archive:${assignment.id}` ? '正在移出…' : '整份作业移出错题本' }}</button></footer>
                </div>
              </details>
            </div>
            <div v-else class="notebook-empty"><div class="notebook-empty-icon"><AppIcon name="book" :size="24"/></div><h3>{{ allMistakes.length ? '没有找到符合条件的作业' : '留一页，给每一次进步' }}</h3><p>{{ allMistakes.length ? '换个关键词，或调整学科与学习进度试试。' : '完成作业诊断后，错题会按作业和错误类别整理在这里。' }}</p><button v-if="allMistakes.length" type="button" @click="resetFilters">查看全部作业 →</button><button v-else type="button" @click="router.push('/student/assignments')">去作业列表 →</button></div>
          </div>
          <div class="notebook-footer-note"><AppIcon name="book" :size="14"/>每学会一类错误，就离下一次做对更近一步。</div>
        </div>
        <MistakePointAssistant v-if="selectedMistake" :mistake="selectedMistake" :related="relatedMistakes" :progress="assistantProgress" :saving-study="workingKey === assistantStudyKey" :fullscreen="assistantFullscreen" @close="closeAssistant" @swap="assistantOnLeft = !assistantOnLeft" @fullscreen="assistantFullscreen = !assistantFullscreen" @review="openDiagnosis($event.submission_id)" @study="toggleAssistantStudy"/>
      </section>

      <MistakeStickyNotes v-else-if="view === 'sticky'" :mistakes="allMistakes" :loading="loading" :student-name="studentName" :split="Boolean(selectedMistake)" :reversed="assistantOnLeft" :fullscreen="assistantFullscreen" :working-key="workingKey" @select-mistake="openAssistant" @study-category="toggleCategoryByPayload" @archive-assignment="archiveById" @start-assignment="router.push('/student/assignments')" @review="openDiagnosis($event.submission_id)">
        <template #assistant><MistakePointAssistant v-if="selectedMistake" :mistake="selectedMistake" :related="relatedMistakes" :progress="assistantProgress" :saving-study="workingKey === assistantStudyKey" :fullscreen="assistantFullscreen" @close="closeAssistant" @swap="assistantOnLeft = !assistantOnLeft" @fullscreen="assistantFullscreen = !assistantFullscreen" @review="openDiagnosis($event.submission_id)" @study="toggleAssistantStudy"/></template>
      </MistakeStickyNotes>

      <MistakeRelationshipMap v-else :mode="view" :mistakes="allMistakes" :student-name="studentName" :split="Boolean(selectedMistake)" :reversed="assistantOnLeft" :fullscreen="assistantFullscreen" @select="openAssistant">
        <template #assistant><MistakePointAssistant v-if="selectedMistake" :mistake="selectedMistake" :related="relatedMistakes" :progress="assistantProgress" :saving-study="workingKey === assistantStudyKey" :fullscreen="assistantFullscreen" @close="closeAssistant" @swap="assistantOnLeft = !assistantOnLeft" @fullscreen="assistantFullscreen = !assistantFullscreen" @review="openDiagnosis($event.submission_id)" @study="toggleAssistantStudy"/></template>
      </MistakeRelationshipMap>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import { useStudentStore } from '../../stores/student'
import type { StudentMistake } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'
import MistakePointAssistant from '../../components/mistake-book/MistakePointAssistant.vue'
import MistakeRelationshipMap from '../../components/mistake-book/MistakeRelationshipMap.vue'
import MistakeStickyNotes from '../../components/mistake-book/MistakeStickyNotes.vue'
import type { IconName } from '../../components/icons/paths'
import { sanitizeStudentCopy } from '../../utils/errorType'
import '../../assets/mistake-book-reference/mistake-notebook.css'
import '../../assets/mistake-book-reference/mistake-sticky-notes.css'
import '../../assets/mistake-book-reference/mistake-mindmap.css'
import '../../assets/mistake-book-reference/mistake-network.css'
import '../../assets/mistake-book-reference/mistake-point-assistant.css'

type NotebookView = 'notebook' | 'sticky' | 'mindmap' | 'network'
interface MistakeCategory { key: string; label: string; items: StudentMistake[]; studied: boolean; similar: StudentMistake['similar_occurrences'] }
interface AssignmentGroup { id: number; title: string; createdAt: string; subject: string; items: StudentMistake[]; categories: MistakeCategory[]; ready: boolean }

const router = useRouter()
const auth = useAuthStore()
const student = useStudentStore()
const allMistakes = ref<StudentMistake[]>([])
const loading = ref(false)
const loadError = ref('')
const actionError = ref('')
const view = ref<NotebookView>('notebook')
const subject = ref('all')
const status = ref<'all' | 'pending' | 'ready'>('all')
const query = ref('')
const sort = ref('recent')
const workingKey = ref('')
const selectedMistake = ref<StudentMistake | null>(null)
const assistantOnLeft = ref(false)
const assistantFullscreen = ref(false)
const removedAssignment = ref<{ id: number; title: string; ids: number[] } | null>(null)
const studentName = computed(() => auth.name || '我的')
const viewOptions: Array<{ key: NotebookView; label: string; icon: IconName }> = [
  { key: 'notebook', label: '卡片笔记', icon: 'book' },
  { key: 'sticky', label: '便利贴', icon: 'file' },
  { key: 'mindmap', label: '思维导图', icon: 'chart' },
  { key: 'network', label: '关联图谱', icon: 'target' },
]
const subjectNames: Record<string, string> = { math: '数学', english: '英语作文', english_exercise: '英语练习', physics: '物理', chemistry: '化学', chinese: '语文', biology: '生物', history: '历史', geography: '地理', politics: '道德与法治', computer_science: '信息科技' }

const subjectOptions = computed(() => Array.from(new Set(allMistakes.value.map((item) => item.question_subject))).map((key) => ({ key, label: subjectName(key) })))
const categoryCount = computed(() => new Set(allMistakes.value.filter((item) => !isStudentSaved(item)).map((item) => `${item.assignment_id}:${item.category_key}`)).size)
const studiedCategoryCount = computed(() => {
  const categories = new Map<string, boolean>()
  for (const item of allMistakes.value.filter((entry) => !isStudentSaved(entry))) {
    const key = `${item.assignment_id}:${item.category_key}`
    categories.set(key, (categories.get(key) ?? true) && item.category_studied)
  }
  return Array.from(categories.values()).filter(Boolean).length
})
const studyPercent = computed(() => categoryCount.value ? Math.round(studiedCategoryCount.value / categoryCount.value * 100) : 0)
const pendingAssignments = computed(() => buildAssignments(allMistakes.value).filter((item) => !item.ready))
const statusOptions = computed(() => {
  const groups = buildAssignments(allMistakes.value)
  return [
    { key: 'all' as const, label: '全部作业', count: groups.length },
    { key: 'pending' as const, label: '待学习', count: groups.filter((item) => !item.ready).length },
    { key: 'ready' as const, label: '已学完', count: groups.filter((item) => item.ready).length },
  ]
})
const visibleAssignments = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase()
  return buildAssignments(allMistakes.value).filter((assignment) => {
    if (subject.value !== 'all' && assignment.subject !== subject.value) return false
    if (status.value === 'pending' && assignment.ready || status.value === 'ready' && !assignment.ready) return false
    if (!needle) return true
    return [assignment.title, ...assignment.categories.flatMap((category) => [category.label, ...category.items.flatMap((item) => [item.error_type, item.knowledge_point, item.question_stem, item.step_text, item.detail])])].filter(Boolean).join(' ').toLocaleLowerCase().includes(needle)
  }).sort((left, right) => {
    if (sort.value === 'oldest') return left.createdAt.localeCompare(right.createdAt)
    if (sort.value === 'priority') {
      const repeated = (group: AssignmentGroup) => group.items.reduce((count, item) => count + item.similar_occurrences.length + Number(item.is_stubborn), 0)
      const difference = repeated(right) - repeated(left)
      if (difference) return difference
    }
    return right.createdAt.localeCompare(left.createdAt)
  })
})
const filtersApplied = computed(() => subject.value !== 'all' || status.value !== 'all' || Boolean(query.value.trim()))
const nextMistake = computed(() => visibleAssignments.value.flatMap((assignment) => assignment.categories.filter((category) => !category.studied).flatMap((category) => category.items))[0])
const relatedMistakes = computed(() => selectedMistake.value ? allMistakes.value.filter((item) => item.question_subject === selectedMistake.value?.question_subject && item.knowledge_point === selectedMistake.value?.knowledge_point && item.category_key === selectedMistake.value?.category_key) : [])
const assistantAssignment = computed(() => selectedMistake.value ? buildAssignments(allMistakes.value).find((item) => item.id === selectedMistake.value?.assignment_id) : undefined)
const assistantProgress = computed(() => ({ completed: assistantAssignment.value?.categories.filter((item) => item.studied).length ?? 0, total: assistantAssignment.value?.categories.length ?? 0, complete: Boolean(assistantAssignment.value?.ready) }))
const assistantStudyKey = computed(() => selectedMistake.value ? studyKey(selectedMistake.value.assignment_id, selectedMistake.value.category_key) : '')

function buildAssignments(items: StudentMistake[]): AssignmentGroup[] {
  const groups = new Map<number, AssignmentGroup>()
  for (const item of items) {
    const group = groups.get(item.assignment_id) ?? { id: item.assignment_id, title: item.assignment_title, createdAt: item.assignment_created_at, subject: item.question_subject, items: [], categories: [], ready: false }
    group.items.push(item)
    let category = group.categories.find((entry) => entry.key === item.category_key)
    if (!category) { category = { key: item.category_key, label: item.category_label || item.error_type, items: [], studied: true, similar: item.similar_occurrences }; group.categories.push(category) }
    category.items.push(item)
    category.studied = category.studied && item.category_studied
    if (item.similar_occurrences.length > category.similar.length) category.similar = item.similar_occurrences
    groups.set(item.assignment_id, group)
  }
  return Array.from(groups.values()).map((group) => {
    group.categories.sort((a, b) => Number(a.studied) - Number(b.studied) || b.items.length - a.items.length || a.label.localeCompare(b.label, 'zh-CN'))
    group.items.sort((a, b) => b.created_at.localeCompare(a.created_at))
    group.ready = group.categories.length > 0 && group.categories.every((item) => item.studied)
    return group
  })
}
function subjectName(value: string) { return subjectNames[value] || value || '其他学科' }
function formatDate(value?: string) { const date = new Date(value || ''); return Number.isNaN(date.getTime()) ? '日期未记录' : date.toLocaleDateString('zh-CN', { year: 'numeric', month: 'numeric', day: 'numeric' }) }
function safe(value: string) { return sanitizeStudentCopy(value) }
function isStudentSaved(item: StudentMistake) { return item.source_kind === 'student_saved' }
function assignmentSummary(assignment: AssignmentGroup) {
  return assignment.items.every(isStudentSaved)
    ? `${assignment.items.length} 道自主收录题目`
    : `${assignment.items.length} 条错题 · ${assignment.categories.length} 类错误`
}
function studyKey(assignmentId: number, categoryKey: string) { return `${assignmentId}:${categoryKey}` }
function setView(next: NotebookView) { view.value = next; closeAssistant(); actionError.value = '' }
function openAssistant(mistake: StudentMistake) { selectedMistake.value = mistake; assistantFullscreen.value = false }
function closeAssistant() { selectedMistake.value = null; assistantOnLeft.value = false; assistantFullscreen.value = false }
function openDiagnosis(submissionId: number) { router.push({ path: '/student/diagnosis', query: { submission_id: submissionId } }) }
function resetFilters() { subject.value = 'all'; status.value = 'all'; query.value = '' }

async function loadMistakes() {
  loading.value = true
  loadError.value = ''
  actionError.value = ''
  try {
    allMistakes.value = await student.fetchMyMistakes(false)
    if (selectedMistake.value) selectedMistake.value = allMistakes.value.find((item) => item.id === selectedMistake.value?.id) || null
  } catch (reason) {
    loadError.value = '错题本加载失败，请确认后端已启动。'
    console.error(reason)
  } finally { loading.value = false }
}
async function toggleCategory(assignment: AssignmentGroup, category: MistakeCategory) {
  await toggleCategoryByPayload({ assignment_id: assignment.id, category_key: category.key, studied: !category.studied })
}
async function toggleCategoryByPayload(payload: { assignment_id: number; category_key: string; studied: boolean }) {
  const key = studyKey(payload.assignment_id, payload.category_key)
  workingKey.value = key
  actionError.value = ''
  try {
    await student.setMistakeCategoryStudied(payload)
    allMistakes.value = allMistakes.value.map((item) => item.assignment_id === payload.assignment_id && item.category_key === payload.category_key ? { ...item, category_studied: payload.studied } : item)
    if (selectedMistake.value?.assignment_id === payload.assignment_id && selectedMistake.value.category_key === payload.category_key) selectedMistake.value = { ...selectedMistake.value, category_studied: payload.studied }
  } catch {
    actionError.value = '学习状态保存失败，请稍后重试。'
  } finally { workingKey.value = '' }
}
async function toggleAssistantStudy() {
  const mistake = selectedMistake.value
  if (!mistake || isStudentSaved(mistake)) return
  const group = assistantAssignment.value?.categories.find((item) => item.key === mistake.category_key)
  if (!group) return
  await toggleCategoryByPayload({ assignment_id: mistake.assignment_id, category_key: mistake.category_key, studied: !group.studied })
}
async function archiveAssignment(assignment: AssignmentGroup) {
  if (!assignment.ready) return
  workingKey.value = `archive:${assignment.id}`
  actionError.value = ''
  try {
    await student.setMistakeAssignmentArchived(assignment.id, true)
    removedAssignment.value = { id: assignment.id, title: assignment.title, ids: assignment.items.map((item) => item.id) }
    closeAssistant()
    await loadMistakes()
  } catch { actionError.value = '整份作业移出失败，请稍后重试。' }
  finally { workingKey.value = '' }
}
async function archiveById(assignmentId: number) {
  const assignment = buildAssignments(allMistakes.value).find((item) => item.id === assignmentId)
  if (assignment) await archiveAssignment(assignment)
}
async function archiveSaved(mistake: StudentMistake) {
  workingKey.value = `archive:${mistake.assignment_id}`
  actionError.value = ''
  try {
    await student.setMistakeArchived(mistake.id, true)
    closeAssistant()
    await loadMistakes()
  } catch { actionError.value = '移出错题本失败，请稍后重试。' }
  finally { workingKey.value = '' }
}
async function restoreAssignment() {
  if (!removedAssignment.value) return
  const removed = removedAssignment.value
  workingKey.value = `restore:${removed.id}`
  actionError.value = ''
  try {
    await student.setMistakeAssignmentArchived(removed.id, false, removed.ids)
    removedAssignment.value = null
    await loadMistakes()
  } catch { actionError.value = '恢复作业失败，请稍后重试。' }
  finally { workingKey.value = '' }
}

onMounted(() => void loadMistakes())
</script>

<style scoped>
.remedi-mistake-book { width: 100%; height: 100dvh; min-height: 0; overflow: hidden; }
.remedi-mistake-book .mistakes-panel { position: relative; width: 100%; height: 100%; min-height: 0; overflow: hidden; }
.remedi-mistake-book .mistake-board-toolbar { position: absolute; z-index: 10; top: 16px; right: 18px; }
.remedi-mistake-book .mistake-notebook { height: 100%; min-height: 0; }
.remedi-mistake-book .mistake-notebook:not(.is-split) .mistake-notebook-content { display: flex; max-width: 1240px; height: 100%; flex-direction: column; overflow: hidden; padding: 68px 42px 18px; }
.remedi-mistake-book .mistake-notebook:not(.is-split) .notebook-header,
.remedi-mistake-book .mistake-notebook:not(.is-split) .notebook-overview,
.remedi-mistake-book .mistake-notebook:not(.is-split) .notebook-footer-note { flex: 0 0 auto; }
.remedi-mistake-book .mistake-notebook:not(.is-split) .notebook-workspace { display: flex; min-height: 0; flex: 1 1 auto; flex-direction: column; }
.remedi-mistake-book .mistake-notebook:not(.is-split) .notebook-results-note { flex: 0 0 auto; }
.remedi-mistake-book .mistake-notebook:not(.is-split) .notebook-assignment-list { min-height: 0; flex: 1 1 auto; overflow-y: auto; overscroll-behavior: contain; }
.remedi-mistake-book .mistake-notebook:not(.is-split) .notebook-empty { min-height: 0; flex: 1 1 auto; }
.remedi-mistake-book .mistake-notebook:not(.is-split) .notebook-footer-note { margin-top: 12px; }
.remedi-mistake-book .mistake-notebook.is-split .mistake-notebook-content { padding: 75px 28px 22px; }
.remedi-mistake-book .mistake-map-viewport-frame, .remedi-mistake-book .mistake-network-frame { height: 100%; min-height: 0; }
.remedi-mistake-book .mistake-map-viewport, .remedi-mistake-book .mistake-network-viewport { height: 100%; min-height: 0; }
.remedi-mistake-book .mistake-network-topic-nav { top: 62px; }
.remedi-mistake-book .notebook-header h1 { color: #334338; font-size: clamp(28px, 3vw, 39px); }
.remedi-mistake-book .notebook-header h1 span { color: #55765c; }
.remedi-mistake-book .notebook-header p { color: #8b9485; }
.remedi-mistake-book .notebook-eyebrow { color: #55765c; }
.remedi-mistake-book .notebook-overview { margin: 24px 0 30px; }
.remedi-mistake-book .notebook-stat, .remedi-mistake-book .notebook-progress { border-color: #e5e8de; background: #fffefa; box-shadow: 0 2px 7px #34432c0a; }
.remedi-mistake-book .notebook-stat-icon, .remedi-mistake-book .notebook-progress-track span { color: #55765c; background: #edf3e8; }
.remedi-mistake-book .notebook-progress-track span { display: block; height: 100%; border-radius: inherit; }
.remedi-mistake-book .notebook-review-button { border-color: #55765c; background: #55765c; }
.remedi-mistake-book .notebook-subjects button.selected, .remedi-mistake-book .notebook-status-tabs button.selected { border-color: #d7e2d0; color: #55765c; background: #edf4e9; }
.remedi-mistake-book .notebook-search:focus-within { border-color: #789579; box-shadow: 0 0 0 3px #edf4e9; }
.remedi-mistake-book .notebook-assignment { border-color: #e2e7dc; background: #fffefa; }
.remedi-mistake-book .notebook-assignment[open] { border-color: #d3dec9; box-shadow: 0 5px 18px #46533508; }
.remedi-mistake-book .notebook-subject-badge { color: #66805d; background: #edf4e8; }
.remedi-mistake-book .notebook-assignment-content { padding: 0 16px 16px; }
.remedi-mistake-book .notebook-category { border-color: #e7e9e2; background: #fffefa; }
.remedi-mistake-book .notebook-category.studied { border-color: #d6e6d8; background: #f7fbf5; }
.remedi-mistake-book .notebook-question-open { display: flex; width: 100%; flex-direction: column; align-items: flex-start; gap: 5px; padding: 8px; border: 0; border-radius: 6px; color: #465247; background: transparent; text-align: left; cursor: pointer; }
.remedi-mistake-book .notebook-question-open:hover, .remedi-mistake-book .notebook-question-open.active { background: #f1f6ed; }
.remedi-mistake-book .notebook-question-open strong { font-size: 12px; }
.remedi-mistake-book .notebook-question-open small, .remedi-mistake-book .notebook-question-detail { color: #8a9486; font-size: 11px; }
.remedi-mistake-book .notebook-question-excerpt { color: #566252; font-size: 12px; }
.remedi-mistake-book .notebook-question-detail { line-height: 1.55; }
.remedi-mistake-book .notebook-category-questions article > button:last-child { display: inline-flex; align-items: center; gap: 4px; padding: 6px; border: 0; color: #66805d; background: transparent; font-size: 11px; white-space: nowrap; cursor: pointer; }
.remedi-mistake-book .notebook-assignment-footer button { border-color: #55765c; background: #55765c; }
.remedi-mistake-book .notebook-footer-note { padding-top: 12px; color: #8b9485; }
.remedi-mistake-book .notebook-action-error { margin: 10px 0; color: #a25e50; font-size: 12px; }
.remedi-mistake-book .mistake-point-assistant { animation: notebook-assistant-enter .22s ease-out both; }
@keyframes notebook-assistant-enter { from { opacity: 0; transform: translateX(8px); } to { opacity: 1; transform: translateX(0); } }
@media (max-width: 960px) {
  .remedi-mistake-book { height: calc(100dvh - 52px); }
  .remedi-mistake-book .mistake-notebook-content { padding: 72px 24px 20px; }
}
@media (max-width: 700px) {
  .remedi-mistake-book .mistake-board-toolbar { top: 10px; right: 10px; left: 10px; justify-content: center; }
  .remedi-mistake-book .mistake-view-switch { max-width: calc(100vw - 72px); overflow-x: auto; }
  .remedi-mistake-book .mistake-view-switch button { min-width: auto; padding-inline: 9px; }
  .remedi-mistake-book .mistake-board-refresh { display: none; }
  .remedi-mistake-book .mistake-notebook:not(.is-split) .mistake-notebook-content { padding: 72px 18px 22px; overflow-y: auto; }
  .remedi-mistake-book .mistake-notebook.is-split { display: flex; flex-direction: column; }
  .remedi-mistake-book .mistake-notebook.is-split .mistake-notebook-content { flex: 0 0 48%; padding: 70px 16px 16px; }
  .remedi-mistake-book .mistake-notebook.is-split .mistake-point-assistant { flex: 1; }
}
</style>
