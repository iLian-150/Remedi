<template>
  <div class="mistake-map-view remedi-mistake-book">
    <main class="mistakes-panel" :class="`is-${view}`" aria-label="学生错题本">
      <div class="mistake-board-toolbar" :class="{ 'with-notebook-filters': view === 'notebook', 'is-split': view === 'notebook' && Boolean(selectedMistake), 'is-reversed': assistantOnLeft }" role="toolbar" aria-label="错题本视图操作">
        <div v-if="view === 'notebook'" class="notebook-status-tabs" role="group" aria-label="按作业学习进度筛选">
          <button v-for="option in statusOptions" :key="option.key" type="button" :class="{ selected: status === option.key }" :aria-pressed="status === option.key" @click="status = option.key">{{ option.label }}<small>{{ option.count }}</small></button>
        </div>
        <div v-if="view === 'notebook'" class="notebook-search-tools">
          <label class="notebook-search"><AppIcon name="file" :size="15"/><input v-model="query" type="search" placeholder="搜索作业、错因、知识点…" aria-label="搜索作业和错因"/><button v-if="query" type="button" aria-label="清空搜索" @click="query = ''"><AppIcon name="x" :size="13"/></button></label>
          <label class="notebook-sort"><select v-model="sort" aria-label="作业排序"><option value="recent">最近作业</option><option value="oldest">最早作业</option><option value="priority">优先看重复错因</option></select></label>
        </div>
        <div class="mistake-view-switch" role="group" aria-label="切换错题本样式">
          <button v-for="item in viewOptions" :key="item.key" type="button" :class="{ selected: view === item.key }" :aria-pressed="view === item.key" @click="setView(item.key)"><AppIcon :name="item.icon" :size="15"/>{{ item.label }}</button>
        </div>
        <button class="mistake-board-refresh" type="button" :disabled="loading" aria-label="刷新错题本" title="刷新错题" @click="loadMistakes"><AppIcon name="refresh" :size="17"/></button>
      </div>

      <div v-if="removedAssignment" class="mistake-removal-notice" role="status">
        <span>已将「{{ removedAssignment.title }}」的整份错题移出，历史记录仍保留。<em v-if="actionError">{{ actionError }}</em></span>
        <button type="button" :disabled="workingKey === `restore:${removedAssignment.id}`" @click="restoreAssignment">{{ workingKey === `restore:${removedAssignment.id}` ? '恢复中…' : '撤销' }}</button>
        <button type="button" class="mistake-notice-close" aria-label="关闭移出提示" @click="removedAssignment = null"><AppIcon name="x" :size="14"/></button>
      </div>
      <p v-if="loadError" class="notebook-action-error" role="alert">{{ loadError }}</p>

      <section v-if="view === 'notebook'" class="mistake-notebook" :class="{ 'is-split': Boolean(selectedMistake), 'is-reversed': assistantOnLeft, 'is-assistant-fullscreen': assistantFullscreen }" aria-label="按作业复习错题本" :aria-busy="loading">
        <div class="mistake-notebook-content scrollbar-on-scroll">
          <div class="notebook-workspace">
            <div class="notebook-results-note" role="status" aria-live="polite"><span>{{ loading ? '正在整理你的错题…' : `共 ${visibleAssignments.length} 份${filtersApplied ? '符合条件的' : '待复习'}作业` }}</span><button v-if="filtersApplied" type="button" @click="resetFilters">重置筛选</button></div>
            <p v-if="actionError && !removedAssignment" class="notebook-action-error" role="alert">{{ actionError }}</p>
            <div v-if="loading" class="notebook-assignment-list notebook-loading" aria-hidden="true"><div v-for="index in 4" :key="index" class="notebook-skeleton"><span/><span/><span/></div></div>
            <div v-else-if="visibleAssignments.length" class="notebook-assignment-list">
              <details v-for="assignment in displayedAssignments" :key="assignment.id" class="notebook-assignment" :open="expandedAssignmentIds.has(assignment.id)" @toggle="onAssignmentToggle(assignment.id, $event)">
                <summary>
                  <span class="notebook-assignment-chevron" aria-hidden="true"><AppIcon name="chevron-down" :size="16"/></span>
                  <span class="notebook-subject-badge"><AppIcon name="book" :size="14"/>{{ subjectName(assignment.subject) }}</span>
                  <span class="notebook-assignment-title"><strong>{{ assignment.title }}</strong><small>{{ formatDate(assignment.createdAt) }} · {{ assignmentSummary(assignment) }}</small></span>
                  <span class="notebook-assignment-progress">{{ assignment.studentSavedOnly ? '自主收录' : `${assignment.studiedCategoryCount}/${assignment.categories.length} 类` }}</span>
                  <span class="notebook-assignment-state" :class="{ ready: assignment.ready }">{{ assignment.studentSavedOnly ? '已收录' : assignment.ready ? '已学完' : '待学习' }}</span>
                </summary>
                <div v-if="expandedAssignmentIds.has(assignment.id)" class="notebook-assignment-content">
                  <section v-for="category in assignment.categories" :key="category.key" class="notebook-category" :class="{ studied: category.studied }">
                    <header class="notebook-category-head"><div><span class="notebook-category-dot"/><div><h4>{{ category.label }}</h4><small>{{ category.itemCount }} 条记录</small></div></div><button v-if="!category.studentSavedOnly" type="button" :class="{ studied: category.studied }" :disabled="workingKey === studyKey(assignment.id, category.key)" @click="toggleCategory(assignment, category)">{{ workingKey === studyKey(assignment.id, category.key) ? '保存中…' : category.studied ? '已学会 · 撤销' : '标记已学会' }}</button></header>
                    <div v-if="category.similar.length" class="notebook-repeat-note"><strong>同类问题再次出现</strong><span>你之前也在这些作业中错过类似题目：</span><div><button v-for="previous in category.similar" :key="previous.id" type="button" @click="openSimilarOriginal(previous)">{{ previous.assignment_title }} · {{ formatDate(previous.assignment_created_at) }} · 回看错题</button></div></div>
                    <div class="notebook-category-questions"><article v-for="mistake in categoryItems(category, assignment.id)" :key="mistake.id">
                      <button type="button" class="notebook-question-open" :class="{ active: selectedMistake?.id === mistake.id }" @click="openAssistant(mistake)"><strong>{{ isStudentSaved(mistake) ? '自主收录题目' : `第 ${mistake.question_order} 题${mistake.step_seq ? ` · 第 ${mistake.step_seq} 步` : ''}` }}</strong><small>{{ mistake.knowledge_point }} · {{ mistake.error_type }}</small><span class="notebook-question-excerpt">{{ mistake.question_stem }}</span><span class="notebook-question-detail">{{ safe(mistake.detail || '') }}</span></button>
                      <button v-if="!isStudentSaved(mistake)" type="button" @click.stop.prevent="openOriginalQuestion(mistake)">查看原题<AppIcon name="arrow-right" :size="12"/></button>
                      <button v-else type="button" :disabled="workingKey === `archive:${mistake.assignment_id}`" @click="archiveSaved(mistake)">{{ workingKey === `archive:${mistake.assignment_id}` ? '正在移出…' : '移出错题本' }}</button>
                    </article></div>
                    <button v-if="displayedCategoryItemCount(assignment.id, category) < category.itemCount" type="button" class="notebook-more-category-items" @click="showMoreCategoryItems(assignment.id, category)">继续显示错题（{{ displayedCategoryItemCount(assignment.id, category) }} / {{ category.itemCount }}）</button>
                  </section>
                  <footer v-if="!assignment.studentSavedOnly" class="notebook-assignment-footer"><span>{{ assignment.ready ? '这份作业的错误类别都已学完。' : `还需学完 ${assignment.categories.length - assignment.studiedCategoryCount} 类，才能移出整份作业。` }}</span><button type="button" :disabled="!assignment.ready || workingKey === `archive:${assignment.id}`" @click="archiveAssignment(assignment)">{{ workingKey === `archive:${assignment.id}` ? '正在移出…' : '整份作业移出错题本' }}</button></footer>
                </div>
              </details>
              <button v-if="displayedAssignments.length < visibleAssignments.length" type="button" class="notebook-more-assignments" @click="showMoreAssignments">继续显示作业（{{ displayedAssignments.length }} / {{ visibleAssignments.length }}）</button>
            </div>
            <div v-else class="notebook-empty"><div class="notebook-empty-icon"><AppIcon name="book" :size="24"/></div><h3>{{ allMistakes.length ? '没有找到符合条件的作业' : '暂无错题' }}</h3><p v-if="allMistakes.length">换个关键词，或调整学习进度试试。</p><button v-if="allMistakes.length" type="button" @click="resetFilters">查看全部作业 <AppIcon name="arrow-right" :size="12"/></button><button v-else type="button" @click="router.push('/student/assignments')">去作业列表 <AppIcon name="arrow-right" :size="12"/></button></div>
          </div>
        </div>
        <MistakePointAssistant v-if="selectedMistake" :mistake="selectedMistake" :related="relatedMistakes" :progress="assistantProgress" :saving-study="workingKey === assistantStudyKey" :fullscreen="assistantFullscreen" @close="closeAssistant" @swap="assistantOnLeft = !assistantOnLeft" @fullscreen="assistantFullscreen = !assistantFullscreen" @open-original="openOriginalQuestion($event)" @study="toggleAssistantStudy"/>
      </section>

      <MistakeStickyNotes v-else-if="view === 'sticky'" :mistakes="allMistakes" :loading="loading" :student-name="studentName" :split="Boolean(selectedMistake)" :reversed="assistantOnLeft" :fullscreen="assistantFullscreen" :working-key="workingKey" @select-mistake="openAssistant" @study-category="toggleCategoryByPayload" @archive-assignment="archiveById" @start-assignment="router.push('/student/assignments')" @review="openOriginalQuestion($event)">
        <template #assistant><MistakePointAssistant v-if="selectedMistake" :mistake="selectedMistake" :related="relatedMistakes" :progress="assistantProgress" :saving-study="workingKey === assistantStudyKey" :fullscreen="assistantFullscreen" @close="closeAssistant" @swap="assistantOnLeft = !assistantOnLeft" @fullscreen="assistantFullscreen = !assistantFullscreen" @open-original="openOriginalQuestion($event)" @study="toggleAssistantStudy"/></template>
      </MistakeStickyNotes>

      <MistakeRelationshipMap v-else :mode="view" :mistakes="allMistakes" :student-name="studentName" :split="Boolean(selectedMistake)" :reversed="assistantOnLeft" :fullscreen="assistantFullscreen" @select="openAssistant">
        <template #assistant><MistakePointAssistant v-if="selectedMistake" :mistake="selectedMistake" :related="relatedMistakes" :progress="assistantProgress" :saving-study="workingKey === assistantStudyKey" :fullscreen="assistantFullscreen" @close="closeAssistant" @swap="assistantOnLeft = !assistantOnLeft" @fullscreen="assistantFullscreen = !assistantFullscreen" @open-original="openOriginalQuestion($event)" @study="toggleAssistantStudy"/></template>
      </MistakeRelationshipMap>
    </main>
    <PreviousMistakeModal :mistake="selectedOriginalMistake" @close="selectedOriginalMistake = null" />
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import { useStudentStore } from '../../stores/student'
import type { RelatedMistake, StudentMistake } from '../../api/types'
import PreviousMistakeModal from '../../components/PreviousMistakeModal.vue'
import AppIcon from '../../components/icons/AppIcon.vue'
import type { IconName } from '../../components/icons/paths'
import { sanitizeStudentCopy } from '../../utils/errorType'
import { getSubjectLabel } from '../../utils/subjectLabels'
import '../../assets/mistake-book.css'

const MistakePointAssistant = defineAsyncComponent(
  () => import('../../components/mistake-book/MistakePointAssistant.vue'),
)
const MistakeRelationshipMap = defineAsyncComponent(
  () => import('../../components/mistake-book/MistakeRelationshipMap.vue'),
)
const MistakeStickyNotes = defineAsyncComponent(
  () => import('../../components/mistake-book/MistakeStickyNotes.vue'),
)

type NotebookView = 'notebook' | 'sticky' | 'mindmap'
interface MistakeCategory { key: string; label: string; itemCount: number; firstItem: StudentMistake | null; items: StudentMistake[]; studied: boolean; studentSavedOnly: boolean; similar: StudentMistake['similar_occurrences'] }
interface AssignmentGroup { id: number; title: string; createdAt: string; subject: string; itemCount: number; categories: MistakeCategory[]; ready: boolean; studentSavedOnly: boolean; studiedCategoryCount: number; priority: number }
type RelatedMistakeIndex = Map<string, Map<string, Map<string, StudentMistake[]>>>
type AssignmentSearchIndex = Map<number, string>
interface NotebookData {
  assignmentGroups: AssignmentGroup[]
  assignmentGroupsById: Map<number, AssignmentGroup>
}

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const student = useStudentStore()
const allMistakes = ref<StudentMistake[]>([])
const loading = ref(false)
const mistakesLoaded = ref(false)
const loadError = ref('')
const actionError = ref('')
const view = ref<NotebookView>('notebook')
const selectedOriginalMistake = ref<RelatedMistake | StudentMistake | null>(null)
const status = ref<'all' | 'pending' | 'ready'>('all')
const query = ref('')
const sort = ref('recent')
const workingKey = ref('')
const selectedMistake = ref<StudentMistake | null>(null)
const expandedAssignmentIds = ref<Set<number>>(new Set())
const notebookAssignmentPageSize = 30
const notebookCategoryPageSize = 25
const visibleAssignmentLimit = ref(notebookAssignmentPageSize)
const categoryItemLimits = ref<Record<string, number>>({})
const assistantOnLeft = ref(false)
const assistantFullscreen = ref(false)
const removedAssignment = ref<{
  id: number
  title: string
  ids: number[]
  items: StudentMistake[]
} | null>(null)
let supplementalStylesPromise: Promise<unknown> | undefined
let viewRequestId = 0
let assistantRequestId = 0
const studentName = computed(() => auth.name || '我的')
const viewOptions: Array<{ key: NotebookView; label: string; icon: IconName }> = [
  { key: 'notebook', label: '卡片笔记', icon: 'book' },
  { key: 'sticky', label: '便利贴', icon: 'file' },
  { key: 'mindmap', label: '思维导图', icon: 'chart' },
]
const dateFormatter = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'numeric', day: 'numeric' })
const relatedMistakeIndexCache = new WeakMap<StudentMistake[], RelatedMistakeIndex>()
const assignmentSearchIndexCache = new WeakMap<StudentMistake[], AssignmentSearchIndex>()

const notebookData = computed(() => buildNotebookData(allMistakes.value))
const assignmentGroups = computed(() => notebookData.value.assignmentGroups)
const assignmentReadiness = computed(() => {
  let pending = 0
  let ready = 0
  for (const assignment of assignmentGroups.value) {
    if (assignment.ready) ready++
    else pending++
  }
  return { pending, ready }
})
const statusOptions = computed(() => {
  const groups = assignmentGroups.value
  return [
    { key: 'all' as const, label: '全部作业', count: groups.length },
    { key: 'pending' as const, label: '待学习', count: assignmentReadiness.value.pending },
    { key: 'ready' as const, label: '已学完', count: assignmentReadiness.value.ready },
  ]
})
// 排序只依赖类别顺序与排序选项；搜索输入变化时复用这份结果。
const sortedAssignments = computed(() => [...assignmentGroups.value].sort((left, right) => {
  if (sort.value === 'oldest') return left.createdAt.localeCompare(right.createdAt)
  if (sort.value === 'priority') {
    const difference = right.priority - left.priority
    if (difference) return difference
  }
  return right.createdAt.localeCompare(left.createdAt)
}))
const visibleAssignments = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase()
  return sortedAssignments.value.filter((assignment) => {
    if (status.value === 'pending' && assignment.ready || status.value === 'ready' && !assignment.ready) return false
    if (!needle) return true
    return assignmentSearchText(assignment).includes(needle)
  })
})
const displayedAssignments = computed(() =>
  visibleAssignments.value.slice(0, visibleAssignmentLimit.value)
)
watch([status, query, sort], () => {
  visibleAssignmentLimit.value = notebookAssignmentPageSize
})
watch(() => view.value === 'notebook' ? visibleAssignments.value : null, (assignments, previous) => {
  if (!assignments) return
  const visibleIds = new Set(assignments.map((assignment) => assignment.id))
  const next = new Set([...expandedAssignmentIds.value].filter((id) => visibleIds.has(id)))
  const firstId = assignments[0]?.id
  if (firstId != null && firstId !== previous?.[0]?.id && !next.has(firstId)) {
    next.add(firstId)
  }
  expandedAssignmentIds.value = next
}, { immediate: true })
const filtersApplied = computed(() => status.value !== 'all' || Boolean(query.value.trim()))
const relatedMistakes = computed(() => {
  const mistake = selectedMistake.value
  if (!mistake) return []
  return getRelatedMistakeIndex(allMistakes.value)
    .get(mistake.question_subject)?.get(mistake.knowledge_point)?.get(mistake.category_key) ?? []
})
const assistantAssignment = computed(() => selectedMistake.value ? notebookData.value.assignmentGroupsById.get(selectedMistake.value.assignment_id) : undefined)
const assistantProgress = computed(() => ({ completed: assistantAssignment.value?.studiedCategoryCount ?? 0, total: assistantAssignment.value?.categories.length ?? 0, complete: Boolean(assistantAssignment.value?.ready) }))
const assistantStudyKey = computed(() => selectedMistake.value ? studyKey(selectedMistake.value.assignment_id, selectedMistake.value.category_key) : '')

function onAssignmentToggle(assignmentId: number, event: Event) {
  const details = event.currentTarget as HTMLDetailsElement | null
  if (!details) return
  const next = new Set(expandedAssignmentIds.value)
  if (details.open) next.add(assignmentId)
  else next.delete(assignmentId)
  expandedAssignmentIds.value = next
}

function showMoreAssignments() {
  visibleAssignmentLimit.value += notebookAssignmentPageSize
}

function getRelatedMistakeIndex(items: StudentMistake[]): RelatedMistakeIndex {
  const cached = relatedMistakeIndexCache.get(items)
  if (cached) return cached

  const index: RelatedMistakeIndex = new Map()
  for (const item of items) {
    let subjectIndex = index.get(item.question_subject)
    if (!subjectIndex) {
      subjectIndex = new Map()
      index.set(item.question_subject, subjectIndex)
    }
    let knowledgePointIndex = subjectIndex.get(item.knowledge_point)
    if (!knowledgePointIndex) {
      knowledgePointIndex = new Map()
      subjectIndex.set(item.knowledge_point, knowledgePointIndex)
    }
    let relatedGroup = knowledgePointIndex.get(item.category_key)
    if (!relatedGroup) {
      relatedGroup = []
      knowledgePointIndex.set(item.category_key, relatedGroup)
    }
    relatedGroup.push(item)
  }
  relatedMistakeIndexCache.set(items, index)
  return index
}

function assignmentSearchText(assignment: AssignmentGroup): string {
  const cached = assignmentSearchIndexCache.get(allMistakes.value)
  if (cached) return cached.get(assignment.id) ?? assignment.title.toLocaleLowerCase()

  const searchPartsByAssignment = new Map<number, Array<string | null | undefined>>()
  for (const group of assignmentGroups.value) {
    searchPartsByAssignment.set(group.id, [group.title, ...group.categories.map((category) => category.label)])
  }
  for (const item of allMistakes.value) {
    const searchParts = searchPartsByAssignment.get(item.assignment_id)
    searchParts?.push(item.error_type, item.knowledge_point, item.question_stem, item.step_text, item.detail)
  }
  const index: AssignmentSearchIndex = new Map()
  for (const [assignmentId, searchParts] of searchPartsByAssignment) {
    index.set(assignmentId, searchParts.filter(Boolean).join(' ').toLocaleLowerCase())
  }
  assignmentSearchIndexCache.set(allMistakes.value, index)
  return index.get(assignment.id) ?? assignment.title.toLocaleLowerCase()
}

function displayedCategoryItemCount(assignmentId: number, category: MistakeCategory): number {
  return Math.min(
    category.itemCount,
    categoryItemLimits.value[studyKey(assignmentId, category.key)] ?? notebookCategoryPageSize,
  )
}
function categoryItems(category: MistakeCategory, assignmentId: number): StudentMistake[] {
  return category.items.slice(0, displayedCategoryItemCount(assignmentId, category))
}
function showMoreCategoryItems(assignmentId: number, category: MistakeCategory) {
  const key = studyKey(assignmentId, category.key)
  categoryItemLimits.value[key] = Math.min(
    category.itemCount,
    displayedCategoryItemCount(assignmentId, category) + notebookCategoryPageSize,
  )
}

function buildNotebookData(items: StudentMistake[]): NotebookData {
  const groups = new Map<number, AssignmentGroup>()
  const categoriesByAssignment = new Map<number, Map<string, MistakeCategory>>()
  for (const item of items) {
    let group = groups.get(item.assignment_id)
    if (!group) {
      group = {
        id: item.assignment_id,
        title: item.assignment_title,
        createdAt: item.assignment_created_at,
        subject: item.question_subject,
        itemCount: 0,
        categories: [],
        ready: false,
        studentSavedOnly: true,
        studiedCategoryCount: 0,
        priority: 0,
      }
      groups.set(item.assignment_id, group)
      categoriesByAssignment.set(item.assignment_id, new Map())
    }
    group.itemCount += 1
    group.studentSavedOnly = group.studentSavedOnly && isStudentSaved(item)
    group.priority += item.similar_occurrences.length + Number(item.is_stubborn)
    const categoryIndex = categoriesByAssignment.get(item.assignment_id)!
    let category = categoryIndex.get(item.category_key)
    if (!category) {
      category = {
        key: item.category_key,
        label: item.category_label || item.error_type,
        itemCount: 0,
        firstItem: item,
        items: [],
        studied: true,
        similar: item.similar_occurrences,
        studentSavedOnly: true,
      }
      categoryIndex.set(item.category_key, category)
      group.categories.push(category)
    }
    category.itemCount += 1
    category.items.push(item)
    if (!category.firstItem) category.firstItem = item
    category.studentSavedOnly = category.studentSavedOnly && isStudentSaved(item)
    category.studied = category.studied && item.category_studied
    if (item.similar_occurrences.length > category.similar.length) category.similar = item.similar_occurrences
  }

  const assignmentGroups = Array.from(groups.values()).map((group) => {
    group.categories.sort((a, b) => Number(a.studied) - Number(b.studied) || b.itemCount - a.itemCount || a.label.localeCompare(b.label, 'zh-CN'))
    group.studiedCategoryCount = group.categories.reduce((count, item) => count + Number(item.studied), 0)
    group.ready = group.categories.length > 0 && group.studiedCategoryCount === group.categories.length
    return group
  })
  return {
    assignmentGroups,
    assignmentGroupsById: groups,
  }
}
function subjectName(value: string) { return getSubjectLabel(value, value || '其他学科') }
function formatDate(value?: string) { const date = new Date(value || ''); return Number.isNaN(date.getTime()) ? '日期未记录' : dateFormatter.format(date) }
function safe(value: string) { return sanitizeStudentCopy(value) }
function isStudentSaved(item: StudentMistake) { return item.source_kind === 'student_saved' }
function assignmentSummary(assignment: AssignmentGroup) {
  return assignment.studentSavedOnly
    ? `${assignment.itemCount} 道自主收录题目`
    : `${assignment.itemCount} 条错题 · ${assignment.categories.length} 类错误`
}
function studyKey(assignmentId: number, categoryKey: string) { return `${assignmentId}:${categoryKey}` }
function ensureSupplementalStyles() {
  if (!supplementalStylesPromise) {
    supplementalStylesPromise = import('../../assets/mistake-book-2.css').catch((error) => {
      supplementalStylesPromise = undefined
      throw error
    })
  }
  return supplementalStylesPromise
}
function setView(next: NotebookView) {
  const requestId = ++viewRequestId
  const activate = () => {
    if (requestId !== viewRequestId) return
    view.value = next
    closeAssistant()
    actionError.value = ''
  }
  if (next !== 'mindmap') { activate(); return }
  void ensureSupplementalStyles().then(activate).catch(() => activate())
}
function openAssistant(mistake: StudentMistake) {
  const requestId = ++assistantRequestId
  const activate = () => {
    if (requestId !== assistantRequestId) return
    selectedMistake.value = mistake
    assistantFullscreen.value = false
  }
  void ensureSupplementalStyles().then(activate).catch(() => activate())
}
function closeAssistant() {
  assistantRequestId += 1
  selectedMistake.value = null
  assistantOnLeft.value = false
  assistantFullscreen.value = false
}
function openOriginalQuestion(mistake: RelatedMistake | StudentMistake) {
  // This action is intentionally local: show the modal without changing the current route.
  selectedOriginalMistake.value = { ...mistake }
}
function openSimilarOriginal(previous: StudentMistake['similar_occurrences'][number]) {
  const fullMistake = allMistakes.value.find((item) => item.id === previous.id)
  if (fullMistake) {
    openOriginalQuestion(fullMistake)
    return
  }
  selectedOriginalMistake.value = {
    id: previous.id,
    submission_id: previous.submission_id,
    question_id: selectedMistake.value?.question_id ?? 0,
    assignment_id: previous.assignment_id,
    assignment_title: previous.assignment_title,
    assignment_created_at: previous.assignment_created_at,
    question_subject: selectedMistake.value?.question_subject ?? '',
    question_stem: previous.question_stem,
    solution_steps: [],
    knowledge_point: selectedMistake.value?.knowledge_point ?? '历史同类错题',
    error_type: selectedMistake.value?.error_type ?? '历史错题',
    detail: null,
    step_seq: null,
    step_text: null,
    created_at: previous.assignment_created_at,
    latest_correction: null,
  }
}
function resetFilters() { status.value = 'all'; query.value = '' }

async function loadMistakes(): Promise<boolean> {
  loading.value = true
  loadError.value = ''
  actionError.value = ''
  try {
    allMistakes.value = await student.fetchMyMistakes(false)
    categoryItemLimits.value = {}
    mistakesLoaded.value = true
    if (selectedMistake.value) selectedMistake.value = allMistakes.value.find((item) => item.id === selectedMistake.value?.id) || null
    openRequestedReview()
    return true
  } catch (reason) {
    const status = typeof reason === 'object' && reason !== null && 'response' in reason
      ? (reason as { response?: { status?: number } }).response?.status
      : undefined
    if (status === 401) {
      loadError.value = '登录状态已失效，请重新登录后再试。'
    } else if (status !== undefined) {
      loadError.value = `错题本加载失败（HTTP ${status}），请刷新重试。`
    } else {
      loadError.value = '暂时无法连接错题本服务，请检查网络后刷新重试。'
    }
    console.error(reason)
    return false
  } finally { loading.value = false }
}
function notifyMistakeReviewChanged(items?: StudentMistake[]) {
  window.dispatchEvent(new CustomEvent('mistake-review-changed', { detail: { items } }))
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
    const category = notebookData.value.assignmentGroupsById
      .get(payload.assignment_id)?.categories
      .find((item) => item.key === payload.category_key)
    for (const item of category?.items ?? []) {
      item.category_studied = payload.studied
    }
    if (selectedMistake.value?.assignment_id === payload.assignment_id && selectedMistake.value.category_key === payload.category_key) {
      selectedMistake.value.category_studied = payload.studied
    }
    notifyMistakeReviewChanged(allMistakes.value)
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
    const archivedIds = await student.setMistakeAssignmentArchived(assignment.id, true)
    if (!archivedIds.length) {
      const refreshed = await loadMistakes()
      notifyMistakeReviewChanged(refreshed ? allMistakes.value : undefined)
      return
    }
    const archivedIdSet = new Set(archivedIds)
    const archivedItems: StudentMistake[] = []
    for (const category of assignment.categories) {
      for (const item of category.items) {
        if (archivedIdSet.has(item.id)) archivedItems.push(item)
      }
    }
    archivedItems.sort((a, b) =>
      b.created_at.localeCompare(a.created_at) || b.id - a.id,
    )
    removedAssignment.value = {
      id: assignment.id,
      title: assignment.title,
      ids: archivedIds,
      items: archivedItems,
    }
    closeAssistant()
    allMistakes.value = allMistakes.value.filter((item) => !archivedIdSet.has(item.id))
    if (archivedItems.length !== archivedIds.length) {
      const refreshed = await loadMistakes()
      notifyMistakeReviewChanged(refreshed ? allMistakes.value : undefined)
    } else notifyMistakeReviewChanged(allMistakes.value)
  } catch { actionError.value = '整份作业移出失败，请稍后重试。' }
  finally { workingKey.value = '' }
}
async function archiveById(assignmentId: number) {
  const assignment = assignmentGroups.value.find((item) => item.id === assignmentId)
  if (assignment) await archiveAssignment(assignment)
}
async function archiveSaved(mistake: StudentMistake) {
  workingKey.value = `archive:${mistake.assignment_id}`
  actionError.value = ''
  try {
    await student.setMistakeArchived(mistake.id, true)
    closeAssistant()
    allMistakes.value = allMistakes.value.filter((item) => item.id !== mistake.id)
    notifyMistakeReviewChanged(allMistakes.value)
  } catch { actionError.value = '移出错题本失败，请稍后重试。' }
  finally { workingKey.value = '' }
}
async function restoreAssignment() {
  if (!removedAssignment.value) return
  const removed = removedAssignment.value
  workingKey.value = `restore:${removed.id}`
  actionError.value = ''
  try {
    const restoredIds = await student.setMistakeAssignmentArchived(removed.id, false, removed.ids)
    removedAssignment.value = null
    if (restoredIds.length === removed.ids.length && removed.items.length === removed.ids.length) {
      const restoredIdSet = new Set(restoredIds)
      const restoredItems = removed.items.filter((item) => restoredIdSet.has(item.id))
      const currentItems = allMistakes.value
      const merged: StudentMistake[] = []
      let currentIndex = 0
      let restoredIndex = 0
      // 当前列表和已移出列表都按创建时间倒序，线性合并可避免重新排序全量错题。
      while (currentIndex < currentItems.length && restoredIndex < restoredItems.length) {
        const current = currentItems[currentIndex]
        const restoredItem = restoredItems[restoredIndex]
        if (current.id === restoredItem.id) {
          merged.push(restoredItem)
          currentIndex += 1
          restoredIndex += 1
        } else if (current.created_at.localeCompare(restoredItem.created_at) >= 0) {
          merged.push(current)
          currentIndex += 1
        } else {
          merged.push(restoredItem)
          restoredIndex += 1
        }
      }
      while (currentIndex < currentItems.length) merged.push(currentItems[currentIndex++])
      while (restoredIndex < restoredItems.length) merged.push(restoredItems[restoredIndex++])
      allMistakes.value = merged
      notifyMistakeReviewChanged(allMistakes.value)
    } else {
      const refreshed = await loadMistakes()
      notifyMistakeReviewChanged(refreshed ? allMistakes.value : undefined)
    }
  } catch { actionError.value = '恢复作业失败，请稍后重试。' }
  finally { workingKey.value = '' }
}

function openRequestedReview() {
  if (!mistakesLoaded.value || typeof route.query.review !== 'string') return
  const requestedId = Number(route.query.review)
  if (!Number.isInteger(requestedId) || requestedId <= 0) return
  const mistake = allMistakes.value.find((item) => item.id === requestedId)
  if (mistake) {
    const assignmentIndex = visibleAssignments.value.findIndex(
      (assignment) => assignment.id === mistake.assignment_id,
    )
    if (assignmentIndex >= visibleAssignmentLimit.value) {
      visibleAssignmentLimit.value =
        Math.ceil((assignmentIndex + 1) / notebookAssignmentPageSize)
        * notebookAssignmentPageSize
    }
    openAssistant(mistake)
  }
  const query = { ...route.query }
  delete query.review
  void router.replace({ path: route.path, query })
}

watch(() => route.query.review, openRequestedReview)

onMounted(() => void loadMistakes())
</script>

<style scoped>
.remedi-mistake-book { width: 100%; max-width: none; height: auto; min-height: 0; flex: 1 1 0; margin: 0; padding: 0 var(--content-frame-gutter); overflow: hidden; }
.remedi-mistake-book .mistakes-panel { position: relative; width: 100%; height: 100%; min-height: 0; overflow: hidden; }
.remedi-mistake-book .mistake-board-toolbar { position: absolute; z-index: 10; top: 16px; right: 18px; }
.remedi-mistake-book .mistake-board-toolbar.with-notebook-filters {
  left: 18px;
  right: 18px;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-surface);
  background: var(--card);
  box-shadow: var(--shadow);
}
.remedi-mistake-book .mistake-board-toolbar.with-notebook-filters .notebook-status-tabs { flex: 0 0 auto; }
.remedi-mistake-book .mistake-board-toolbar.with-notebook-filters .notebook-search-tools {
  width: auto;
  min-width: 0;
  flex: 1 1 260px;
  gap: 8px;
  margin-left: 0;
}
.remedi-mistake-book .mistake-board-toolbar.with-notebook-filters .notebook-search { width: auto; min-width: 150px; flex: 1 1 240px; }
.remedi-mistake-book .mistake-board-toolbar.with-notebook-filters .notebook-sort select { width: 160px; }
.remedi-mistake-book .mistake-board-toolbar.with-notebook-filters .mistake-view-switch {
  flex: 0 0 auto;
  padding: 3px;
  border: 0;
  background: transparent;
  box-shadow: none;
}
.remedi-mistake-book .mistake-board-toolbar.with-notebook-filters .mistake-board-refresh { flex: 0 0 auto; box-shadow: none; }
.remedi-mistake-book .mistake-board-toolbar.with-notebook-filters.is-split {
  flex-wrap: wrap;
  justify-content: flex-start;
}
.remedi-mistake-book .mistake-board-toolbar.with-notebook-filters.is-split .mistake-view-switch { margin-left: auto; }
.remedi-mistake-book .mistake-notebook { height: 100%; min-height: 0; }
.remedi-mistake-book .mistake-notebook:not(.is-split) .mistake-notebook-content { display: block; max-width: none; height: 100%; overflow-x: hidden; overflow-y: auto; overscroll-behavior-y: contain; padding: calc(64px + var(--content-frame-gutter)) var(--content-frame-gutter) var(--content-frame-gutter); }
.remedi-mistake-book .mistake-notebook:not(.is-split) .notebook-assignment-list { overflow: visible; }
.remedi-mistake-book .mistake-notebook.is-split .mistake-notebook-content { padding: 112px var(--content-frame-gutter) var(--content-frame-gutter); }
.remedi-mistake-book .mistake-map-viewport-frame, .remedi-mistake-book .mistake-network-frame { height: 100%; min-height: 0; }
.remedi-mistake-book .mistake-map-viewport, .remedi-mistake-book .mistake-network-viewport { height: 100%; min-height: 0; }
.remedi-mistake-book .mistake-network-topic-nav { top: 62px; }
.remedi-mistake-book .notebook-header h1 { color: var(--text); font-size: clamp(28px, 3vw, 39px); }
.remedi-mistake-book .notebook-header h1 span { color: var(--primary); }
.remedi-mistake-book .notebook-eyebrow { color: var(--primary); }
.remedi-mistake-book .notebook-status-tabs button.selected { border-color: var(--blue-bg); color: var(--primary); background: var(--primary-50); }
.remedi-mistake-book .notebook-search:focus-within { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-50); }
.remedi-mistake-book .notebook-assignment { border-color: var(--border); background: var(--card); }
.remedi-mistake-book .notebook-assignment[open] { border-color: var(--blue-bg); box-shadow: var(--shadow-md); }
.remedi-mistake-book .notebook-subject-badge { color: var(--primary); background: var(--primary-50); }
.remedi-mistake-book .notebook-assignment-content { padding: 0 16px 16px; }
.remedi-mistake-book .notebook-category { border-color: var(--border); background: var(--card); }
.remedi-mistake-book .notebook-category.studied { border-color: var(--green-bg); background: var(--card); }
.remedi-mistake-book .notebook-question-open { display: flex; width: 100%; flex-direction: column; align-items: flex-start; gap: 5px; padding: 8px; border: 0; border-radius: var(--radius-detail); color: var(--text); background: transparent; text-align: left; cursor: pointer; }
.remedi-mistake-book .notebook-question-open:hover, .remedi-mistake-book .notebook-question-open.active { background: var(--primary-50); }
.remedi-mistake-book .notebook-question-open strong { font-size: 12px; }
.remedi-mistake-book .notebook-question-open small, .remedi-mistake-book .notebook-question-detail { color: var(--text-3); font-size: 11px; }
.remedi-mistake-book .notebook-question-excerpt { color: var(--text-2); font-size: 12px; }
.remedi-mistake-book .notebook-question-detail { line-height: 1.55; }
.remedi-mistake-book .notebook-category-questions article > button:last-child { display: inline-flex; align-items: center; gap: 4px; padding: 6px; border: 0; color: var(--primary); background: transparent; font-size: 11px; white-space: nowrap; cursor: pointer; }
/* ---------- 错题行布局修复（v0.13.0）：全局旧样式按「article > div + 右列按钮」的
   旧 DOM 写，把题目按钮和「查看原题」都钉在 grid 第 2 列同一格里互相重叠，
   题目还点不动。这里按现在的 DOM 改回横向 flex：题目按钮占满左侧、查看原题在右。 */
.remedi-mistake-book .notebook-category-questions article { display: flex; align-items: flex-start; gap: 10px; box-sizing: border-box; width: 100%; min-width: 0; max-width: 100%; overflow: hidden; }
.remedi-mistake-book .notebook-category-questions article > .notebook-question-open { box-sizing: border-box; width: auto; max-width: 100%; flex: 1 1 0%; min-width: 0; overflow: hidden; grid-column: auto; grid-row: auto; }
.remedi-mistake-book .notebook-category-questions article > .notebook-question-open > * { box-sizing: border-box; width: 100%; max-width: 100%; min-width: 0; overflow-wrap: anywhere; white-space: normal; }
.remedi-mistake-book .notebook-category-questions article > button:last-child { box-sizing: border-box; flex: 0 0 auto; grid-column: auto; grid-row: auto; margin-top: 4px; }
.remedi-mistake-book .notebook-question-excerpt, .remedi-mistake-book .notebook-question-detail { display: -webkit-box; width: 100%; overflow: hidden; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.remedi-mistake-book .notebook-assignment-content, .remedi-mistake-book .notebook-category, .remedi-mistake-book .notebook-category-questions { box-sizing: border-box; min-width: 0; max-width: 100%; }
.remedi-mistake-book .notebook-assignment-footer button { border-color: var(--primary); background: var(--primary); }
.remedi-mistake-book .notebook-action-error { margin: 10px 0; color: var(--red-strong); font-size: 12px; }
.remedi-mistake-book .mistake-point-assistant { animation: notebook-assistant-enter .22s ease-out both; }
@keyframes notebook-assistant-enter { from { opacity: 0; transform: translateX(8px); } to { opacity: 1; transform: translateX(0); } }
@media (max-width: 960px) {
  .remedi-mistake-book { height: calc(100dvh - 52px); padding: 0 var(--content-frame-gutter-compact); }
  .remedi-mistake-book .mistake-notebook-content { padding: 72px var(--content-frame-gutter-compact) var(--content-frame-gutter-compact); }
}
@media (max-width: 700px) {
  .remedi-mistake-book .mistake-board-toolbar { top: 10px; right: 10px; left: 10px; justify-content: center; }
  .remedi-mistake-book .mistake-view-switch { max-width: calc(100vw - 72px); overflow-x: auto; }
  .remedi-mistake-book .mistake-view-switch button { min-width: auto; padding-inline: 9px; }
  .remedi-mistake-book .mistake-board-refresh { display: none; }
  .remedi-mistake-book .mistake-notebook:not(.is-split) .mistake-notebook-content { padding: 66px var(--content-frame-gutter-compact) var(--content-frame-gutter-compact); }
  .remedi-mistake-book .mistake-notebook.is-split { display: flex; flex-direction: column; }
  .remedi-mistake-book .mistake-notebook.is-split .mistake-notebook-content { flex: 0 0 48%; padding: 66px var(--content-frame-gutter-compact) var(--content-frame-gutter-compact); }
  .remedi-mistake-book .mistake-notebook.is-split .mistake-point-assistant { flex: 1; }
}

/* 错题本统一视觉：保持各视图的数据和交互，只调整层级、留白与表面样式。 */
.remedi-mistake-book .mistakes-panel {
  border-radius: 0;
  background: transparent;
}

.remedi-mistake-book .mistake-board-toolbar {
  top: 20px;
  right: 22px;
  gap: 8px;
}

.remedi-mistake-book .mistake-view-switch {
  gap: 3px;
  padding: 4px;
  border: 1px solid var(--border);
  border-radius: var(--radius-surface);
  background: var(--card);
  box-shadow: var(--shadow);
}

.remedi-mistake-book .mistake-view-switch button {
  display: inline-flex;
  min-height: 36px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 7px 12px;
  border-radius: var(--radius-standard);
  color: var(--text-2);
  font-size: 12px;
  font-weight: 600;
  transition: color .18s ease, background-color .18s ease, box-shadow .18s ease;
}

.remedi-mistake-book .mistake-view-switch button.selected {
  color: var(--primary);
  background: var(--primary-50);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--primary) 10%, transparent);
}

.remedi-mistake-book .mistake-board-refresh {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-standard);
  color: var(--text-2);
  background: var(--card);
  box-shadow: var(--shadow);
}

.remedi-mistake-book .mistake-board-refresh:hover:not(:disabled) {
  border-color: var(--border-strong);
  color: var(--primary);
  background: var(--primary-50);
}

.remedi-mistake-book .mistake-removal-notice {
  border: 1px solid var(--border);
  border-radius: var(--radius-surface);
  background: var(--card);
  box-shadow: var(--shadow);
}

/* 卡片笔记 */
.remedi-mistake-book .mistake-notebook:not(.is-split) .mistake-notebook-content {
  max-width: none;
  padding: calc(40px + var(--content-frame-gutter)) var(--content-frame-gutter) var(--content-frame-gutter);
}

.remedi-mistake-book .notebook-workspace {
  min-width: 0;
}

.remedi-mistake-book .notebook-filterbar {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-surface);
  background: var(--card);
  box-shadow: var(--shadow);
}

.remedi-mistake-book .notebook-status-tabs {
  flex: 0 0 auto;
  gap: 3px;
  padding: 4px;
  border-radius: var(--radius-standard);
  background: var(--surface-2);
  white-space: nowrap;
}

.remedi-mistake-book .notebook-status-tabs button {
  min-height: 36px;
  gap: 7px;
  padding: 7px 11px;
  border-radius: var(--radius-standard);
  color: var(--text-2);
  font-size: 12px;
  font-weight: 600;
}

.remedi-mistake-book .notebook-status-tabs button:hover:not(.selected) {
  color: var(--text);
  background: var(--card);
}

.remedi-mistake-book .notebook-status-tabs button.selected {
  color: var(--primary);
  background: var(--card);
  box-shadow: var(--shadow);
}

.remedi-mistake-book .notebook-search-tools {
  min-width: 0;
  flex: 0 1 auto;
  gap: 8px;
  margin-left: auto;
}

.remedi-mistake-book .notebook-search,
.remedi-mistake-book .notebook-sort select {
  min-height: 40px;
  border: 1px solid var(--border);
  border-radius: var(--radius-standard);
  background: var(--surface-2);
  transition: border-color .16s ease, box-shadow .16s ease, background-color .16s ease;
}

.remedi-mistake-book .notebook-search {
  width: clamp(220px, 24vw, 340px);
  min-width: 180px;
  flex: 0 1 340px;
  padding: 0 11px;
}

.remedi-mistake-book .notebook-search:focus-within,
.remedi-mistake-book .notebook-sort select:focus-visible {
  border-color: var(--primary);
  background: var(--card);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 12%, transparent);
}

.remedi-mistake-book .notebook-search input {
  font-size: 13px;
}

.remedi-mistake-book .notebook-sort select {
  width: 170px;
  flex: 0 0 auto;
  min-height: 40px;
  padding: 8px 30px 8px 11px;
  color: var(--text-strong);
  font-size: 12px;
}

.remedi-mistake-book .notebook-results-note {
  margin: 16px 4px;
  color: var(--text-2);
  font-size: 12px;
}

.remedi-mistake-book .notebook-results-note button {
  border-radius: var(--radius-standard);
  color: var(--primary);
  font-weight: 650;
}

.remedi-mistake-book .notebook-assignment-list {
  display: grid;
  gap: 12px;
}

.remedi-mistake-book .notebook-assignment {
  overflow: clip;
  border: 1px solid var(--border);
  border-radius: var(--radius-surface);
  background: var(--card);
  box-shadow: var(--shadow);
  transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease;
}

.remedi-mistake-book .notebook-assignment:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-md);
}

.remedi-mistake-book .notebook-assignment[open] {
  border-color: color-mix(in srgb, var(--primary) 25%, var(--border));
  box-shadow: var(--shadow-md);
}

.remedi-mistake-book .notebook-assignment > summary {
  grid-template-columns: 32px auto minmax(0, 1fr) auto auto;
  gap: 12px;
  min-height: 82px;
  padding: 14px 18px;
}

.remedi-mistake-book .notebook-assignment-chevron {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: var(--radius-standard);
  color: var(--text-2);
  background: var(--surface-2);
  transition: transform .18s ease, color .18s ease, background-color .18s ease;
}

.remedi-mistake-book .notebook-assignment[open] .notebook-assignment-chevron {
  color: var(--primary);
  background: var(--primary-50);
  transform: rotate(180deg);
}

.remedi-mistake-book .notebook-subject-badge {
  min-height: 28px;
  padding: 5px 9px;
  border-radius: var(--radius-standard);
  font-size: 11px;
  font-weight: 650;
}

.remedi-mistake-book .notebook-assignment-title strong {
  color: var(--text);
  font-size: 14px;
  font-weight: 680;
}

.remedi-mistake-book .notebook-assignment-title small {
  margin-top: 4px;
  color: var(--text-3);
  font-size: 11px;
}

.remedi-mistake-book .notebook-assignment-progress {
  color: var(--text-2);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.remedi-mistake-book .notebook-assignment-state {
  padding: 5px 9px;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  color: var(--text-2);
  background: var(--surface-2);
  font-size: 10px;
  font-weight: 650;
}

.remedi-mistake-book .notebook-assignment-state.ready {
  border-color: var(--green-border);
  color: var(--green-strong);
  background: var(--green-bg);
}

.remedi-mistake-book .notebook-assignment-content {
  gap: 10px;
  padding: 0 18px 18px 62px;
}

.remedi-mistake-book .notebook-category {
  padding: 14px;
  border-color: var(--border);
  border-radius: var(--radius-surface);
  background: var(--surface-2);
}

.remedi-mistake-book .notebook-category-head h4 {
  color: var(--text);
  font-size: 13px;
}

.remedi-mistake-book .notebook-category-dot {
  width: 8px;
  height: 8px;
  background: var(--primary);
}

.remedi-mistake-book .notebook-category.studied .notebook-category-dot {
  background: var(--green);
}

.remedi-mistake-book .notebook-category-head button {
  min-height: 34px;
  padding: 7px 10px;
  border-radius: var(--radius-standard);
  color: var(--primary);
  background: var(--card);
  font-size: 11px;
  font-weight: 650;
}

.remedi-mistake-book .notebook-category-head button.studied {
  border-color: var(--green-border);
  color: var(--green-strong);
  background: var(--green-bg);
}

.remedi-mistake-book .notebook-category-questions article {
  gap: 8px;
  padding: 5px;
  border: 1px solid var(--border);
  border-radius: var(--radius-standard);
  background: var(--card);
  transition: border-color .16s ease, background-color .16s ease;
}

.remedi-mistake-book .notebook-category-questions article:focus-within,
.remedi-mistake-book .notebook-category-questions article:hover {
  border-color: color-mix(in srgb, var(--primary) 28%, var(--border));
  background: color-mix(in srgb, var(--primary-50) 32%, var(--card));
}

.remedi-mistake-book .notebook-question-open {
  gap: 4px;
  padding: 9px;
  border-radius: var(--radius-standard);
}

.remedi-mistake-book .notebook-question-open:hover,
.remedi-mistake-book .notebook-question-open.active {
  background: var(--primary-50);
}

.remedi-mistake-book .notebook-question-open strong {
  color: var(--text-strong);
  font-size: 12px;
}

.remedi-mistake-book .notebook-question-open small,
.remedi-mistake-book .notebook-question-detail {
  color: var(--text-3);
  font-size: 11px;
}

.remedi-mistake-book .notebook-question-excerpt {
  color: var(--text-2);
  font-size: 12px;
}

.remedi-mistake-book .notebook-category-questions article > button:last-child {
  min-height: 32px;
  margin: 0 5px 0 0;
  padding: 6px 9px;
  border: 1px solid var(--border);
  border-radius: var(--radius-standard);
  color: var(--text-2);
  background: var(--surface-2);
  font-size: 11px;
}

.remedi-mistake-book .notebook-category-questions article > button:last-child:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-50);
}

.remedi-mistake-book .notebook-more-category-items,
.remedi-mistake-book .notebook-more-assignments,
:deep(.sticky-list-more) {
  min-height: 38px;
  padding: 8px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-standard);
  color: var(--primary);
  background: var(--card);
  font-size: 12px;
  font-weight: 650;
  transition: border-color .16s ease, background-color .16s ease;
}

.remedi-mistake-book .notebook-more-category-items:hover,
.remedi-mistake-book .notebook-more-assignments:hover,
:deep(.sticky-list-more:hover) {
  border-color: var(--primary);
  background: var(--primary-50);
}

.remedi-mistake-book .notebook-assignment-footer {
  padding-top: 10px;
  color: var(--text-2);
  font-size: 11px;
}

.remedi-mistake-book .notebook-assignment-footer button {
  min-height: 36px;
  padding: 8px 12px;
  border-radius: var(--radius-standard);
  font-size: 11px;
  font-weight: 650;
}

.remedi-mistake-book .notebook-empty {
  margin-top: 10px;
  padding: 52px 24px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-panel);
  background: var(--card);
  text-align: center;
}

.remedi-mistake-book .notebook-empty-icon {
  color: var(--primary);
  background: var(--primary-50);
}

/* 便利贴视图：保留科目色彩，用规整卡片替代旋转纸片和装饰胶带。 */
.remedi-mistake-book :deep(.mistake-sticky-notes) {
  height: 100%;
  min-height: 0;
}

.remedi-mistake-book :deep(.sticky-notes-inner) {
  max-width: 1320px;
  padding: calc(40px + var(--content-frame-gutter)) var(--content-frame-gutter) var(--content-frame-gutter);
}

.remedi-mistake-book :deep(.sticky-notes-header) {
  max-width: 720px;
}

.remedi-mistake-book :deep(.sticky-notes-kicker) {
  color: var(--primary);
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0;
}

.remedi-mistake-book :deep(.sticky-notes-kicker span) {
  color: var(--primary);
}

.remedi-mistake-book :deep(.sticky-notes-header h1) {
  margin: 11px 0 6px;
  color: var(--text);
  font-size: clamp(27px, 2.6vw, 35px);
  font-weight: 730;
  letter-spacing: -.04em;
}

.remedi-mistake-book :deep(.sticky-notes-header p) {
  color: var(--text-2);
  font-size: 13px;
}

.remedi-mistake-book :deep(.sticky-notes-breadcrumb) {
  gap: 9px;
  margin-top: 20px;
  padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-standard);
  background: var(--card);
  width: fit-content;
  max-width: 100%;
}

.remedi-mistake-book :deep(.sticky-notes-breadcrumb button) {
  color: var(--text-2);
  font-weight: 600;
}

.remedi-mistake-book :deep(.sticky-notes-breadcrumb [aria-current="page"]) {
  color: var(--primary);
}

.remedi-mistake-book :deep(.sticky-notes-grid) {
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 248px), 1fr));
  gap: 16px;
  margin-top: 24px;
}

.remedi-mistake-book :deep(.sticky-note) {
  min-height: 210px;
  padding: 22px 20px 18px;
  border: 1px solid color-mix(in srgb, var(--note-paper) 45%, var(--border));
  border-left: 3px solid color-mix(in srgb, var(--note-paper) 76%, var(--primary));
  border-radius: var(--radius-surface);
  color: var(--text);
  background: color-mix(in srgb, var(--note-paper) 32%, var(--card));
  box-shadow: var(--shadow);
  transform: none;
  transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}

.remedi-mistake-book :deep(.sticky-note::before),
.remedi-mistake-book :deep(.sticky-note::after) {
  display: none;
}

.remedi-mistake-book :deep(.sticky-note:hover) {
  border-color: color-mix(in srgb, var(--primary) 24%, var(--border));
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.remedi-mistake-book :deep(.sticky-note.is-studied) {
  border-left-color: var(--green);
}

.remedi-mistake-book :deep(.sticky-note-index) {
  color: var(--text-3);
  font-size: 10px;
  letter-spacing: .06em;
}

.remedi-mistake-book :deep(.sticky-note-title) {
  margin: 16px 0 11px;
  color: var(--text);
  font-size: 22px;
  font-weight: 700;
}

.remedi-mistake-book :deep(.sticky-note-rule) {
  width: 30px;
  height: 3px;
  margin: 0 0 12px;
  color: var(--primary);
  background: var(--primary);
  opacity: .55;
}

.remedi-mistake-book :deep(.sticky-note-stat) {
  color: var(--text-2);
  font-size: 12px;
}

.remedi-mistake-book :deep(.sticky-note-stat b) {
  color: var(--text);
  font-size: 15px;
  font-variant-numeric: tabular-nums;
}

.remedi-mistake-book :deep(.sticky-note-tags) {
  color: var(--text-3);
}

.remedi-mistake-book :deep(.sticky-note-foot) {
  margin-top: auto;
  padding-top: 13px;
  border-top: 1px solid color-mix(in srgb, var(--border) 76%, transparent);
  color: var(--text-2);
  font-size: 11px;
  font-weight: 600;
}

.remedi-mistake-book :deep(.sticky-note-foot svg) {
  color: var(--primary);
}

.remedi-mistake-book :deep(.sticky-notes-empty) {
  margin-top: 28px;
  padding: 44px 24px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-panel);
  background: var(--card);
}

.remedi-mistake-book :deep(.sticky-notes-empty-icon) {
  color: var(--primary);
  background: var(--primary-50);
}

.remedi-mistake-book :deep(.sticky-notes-empty h2) {
  color: var(--text);
}

.remedi-mistake-book :deep(.sticky-notes-empty p) {
  color: var(--text-2);
}

.remedi-mistake-book :deep(.sticky-notes-empty button) {
  min-height: 40px;
  padding: 9px 14px;
  border-radius: var(--radius-standard);
  background: var(--primary);
  font-weight: 650;
}

.remedi-mistake-book :deep(.sticky-detail-summary) {
  margin-top: 22px;
  padding: 15px 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius-surface);
  color: var(--text-2);
  background: var(--card);
  box-shadow: var(--shadow);
}

.remedi-mistake-book :deep(.sticky-detail-summary strong) {
  color: var(--primary);
  font-variant-numeric: tabular-nums;
}

.remedi-mistake-book :deep(.sticky-assignment-list) {
  max-width: none;
  gap: 14px;
  margin-top: 14px;
  padding: 0 0 20px;
}

.remedi-mistake-book :deep(.sticky-assignment) {
  padding: 20px;
  border: 1px solid var(--border);
  border-radius: var(--radius-surface);
  color: var(--text);
  background: var(--card);
  box-shadow: var(--shadow);
  transform: none;
}

.remedi-mistake-book :deep(.sticky-assignment::before),
.remedi-mistake-book :deep(.sticky-assignment::after),
.remedi-mistake-book :deep(.sticky-question::before),
.remedi-mistake-book :deep(.sticky-question::after) {
  display: none;
}

.remedi-mistake-book :deep(.sticky-assignment.is-studied) {
  border-color: var(--green-border);
}

.remedi-mistake-book :deep(.sticky-assignment-head h2) {
  color: var(--text);
  font-size: 18px;
}

.remedi-mistake-book :deep(.sticky-assignment-head p) {
  color: var(--text-2);
}

.remedi-mistake-book :deep(.sticky-assignment-state) {
  padding: 5px 9px;
  border-color: var(--border);
  border-radius: var(--radius-pill);
  color: var(--text-2);
  background: var(--surface-2);
  font-weight: 650;
}

.remedi-mistake-book :deep(.sticky-assignment.is-studied .sticky-assignment-state) {
  border-color: var(--green-border);
  color: var(--green-strong);
  background: var(--green-bg);
}

.remedi-mistake-book :deep(.sticky-assignment-questions) {
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 260px), 1fr));
  gap: 12px;
  margin-top: 16px;
}

.remedi-mistake-book :deep(.sticky-question) {
  min-height: 170px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-surface);
  color: var(--text);
  background: color-mix(in srgb, var(--note-paper) 24%, var(--card));
  box-shadow: none;
  transform: none;
  transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease;
}

.remedi-mistake-book :deep(.sticky-question:hover),
.remedi-mistake-book :deep(.sticky-question.is-current) {
  border-color: color-mix(in srgb, var(--primary) 35%, var(--border));
  box-shadow: var(--shadow);
  transform: translateY(-1px);
}

.remedi-mistake-book :deep(.sticky-question-head strong) {
  color: var(--text-strong);
  font-size: 12px;
}

.remedi-mistake-book :deep(.sticky-question-head span),
.remedi-mistake-book :deep(.sticky-question-diagnosis) {
  color: var(--text-2);
}

.remedi-mistake-book :deep(.sticky-question-excerpt) {
  color: var(--text);
}

.remedi-mistake-book :deep(.sticky-question-actions) {
  gap: 8px 14px;
  padding-top: 12px;
}

.remedi-mistake-book :deep(.sticky-question-actions button) {
  color: var(--primary);
  font-size: 11px;
}

.remedi-mistake-book :deep(.sticky-question-actions button:hover) {
  text-decoration: none;
}

.remedi-mistake-book :deep(.sticky-assignment-actions) {
  gap: 8px;
  padding-top: 13px;
  border-color: var(--border);
}

.remedi-mistake-book :deep(.sticky-assignment-actions button) {
  min-height: 36px;
  padding: 7px 11px;
  border-color: var(--border);
  border-radius: var(--radius-standard);
  color: var(--text-strong);
  background: var(--card);
  font-weight: 600;
}

.remedi-mistake-book :deep(.sticky-assignment-actions button:hover:not(:disabled)) {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-50);
}

/* 思维导图与关联图 */
.remedi-mistake-book :deep(.mistake-map-section),
.remedi-mistake-book :deep(.mistake-network) {
  border-radius: var(--radius-panel);
  background: transparent !important;
}

.remedi-mistake-book :deep(.mistake-map-viewport) {
  border: 0 !important;
  border-radius: 0;
  background: transparent !important;
  box-shadow: none !important;
}

.remedi-mistake-book :deep(.mistake-network-viewport) {
  border-color: var(--border);
  border-radius: var(--radius-panel);
  background: var(--surface-2);
  box-shadow: inset 0 1px 2px color-mix(in srgb, var(--text) 3%, transparent);
}

.remedi-mistake-book :deep(.mistake-map-stage),
.remedi-mistake-book :deep(.mistake-map-canvas) {
  background: transparent !important;
}

.remedi-mistake-book :deep(.mistake-map-stage) {
  min-width: 100% !important;
  min-height: 100% !important;
}

.remedi-mistake-book :deep(.mistake-map-canvas) {
  background-image: none !important;
}

.remedi-mistake-book :deep(.mistake-map-stage),
.remedi-mistake-book :deep(.mistake-map-canvas),
.remedi-mistake-book :deep(.mistake-network-stage),
.remedi-mistake-book :deep(.mistake-network-canvas) {
  background-color: var(--surface-2);
}

.remedi-mistake-book :deep(.mistake-map-canvas) {
  background-image: radial-gradient(color-mix(in srgb, var(--border-strong) 56%, transparent) 1px, transparent 1px);
  background-size: 24px 24px;
}

.remedi-mistake-book :deep(.mistake-map-root) {
  border: 1px solid color-mix(in srgb, var(--primary) 30%, var(--border));
  border-radius: var(--radius-panel);
  color: var(--card);
  background: linear-gradient(145deg, var(--primary), var(--primary-dark));
  box-shadow: var(--shadow-md);
}

.remedi-mistake-book :deep(.mistake-map-root > span),
.remedi-mistake-book :deep(.mistake-map-root small) {
  color: color-mix(in srgb, var(--card) 78%, transparent);
}

.remedi-mistake-book :deep(.mistake-map-root strong) {
  font-family: var(--font);
  font-size: 21px;
  letter-spacing: -.03em;
}

.remedi-mistake-book :deep(.mistake-map-branch),
.remedi-mistake-book :deep(.mistake-map-topic-node),
.remedi-mistake-book :deep(.mistake-map-leaf-node),
.remedi-mistake-book :deep(.mistake-network-node) {
  border-color: var(--border);
  border-radius: var(--radius-surface);
  color: var(--text);
  background: var(--card);
  box-shadow: var(--shadow);
}

.remedi-mistake-book :deep(.mistake-map-branch:hover),
.remedi-mistake-book :deep(.mistake-map-branch.selected),
.remedi-mistake-book :deep(.mistake-map-topic-node:hover),
.remedi-mistake-book :deep(.mistake-map-topic-node.selected),
.remedi-mistake-book :deep(.mistake-map-leaf-node:hover),
.remedi-mistake-book :deep(.mistake-map-leaf-node.selected),
.remedi-mistake-book :deep(.mistake-network-node:hover),
.remedi-mistake-book :deep(.mistake-network-node.selected) {
  border-color: color-mix(in srgb, var(--accent, var(--primary)) 38%, var(--border));
  background: color-mix(in srgb, var(--accent, var(--primary)) 8%, var(--card));
  box-shadow: var(--shadow-md);
}

.remedi-mistake-book :deep(.mistake-map-branch small),
.remedi-mistake-book :deep(.mistake-map-topic-node small),
.remedi-mistake-book :deep(.mistake-map-leaf-node small),
.remedi-mistake-book :deep(.mistake-network-node small) {
  color: var(--text-2);
}

.remedi-mistake-book :deep(.mistake-map-tools),
.remedi-mistake-book :deep(.mistake-network-controls),
.remedi-mistake-book :deep(.mistake-network-topic-nav),
.remedi-mistake-book :deep(.mistake-map-branch-nav) {
  border-color: var(--border);
  border-radius: var(--radius-surface);
  background: var(--card);
  box-shadow: var(--shadow);
  backdrop-filter: none;
}

.remedi-mistake-book :deep(.mistake-map-tools button),
.remedi-mistake-book :deep(.mistake-network-controls button),
.remedi-mistake-book :deep(.mistake-network-topic-nav button),
.remedi-mistake-book :deep(.mistake-map-branch-nav button) {
  border-radius: var(--radius-standard);
}

.remedi-mistake-book :deep(.mistake-map-tools .mistake-map-home),
.remedi-mistake-book :deep(.mistake-network-controls .mistake-network-center-button) {
  color: var(--primary);
  background: var(--primary-50);
}

.remedi-mistake-book :deep(.mistake-network-topic-nav button.selected),
.remedi-mistake-book :deep(.mistake-map-branch-nav button.selected) {
  color: var(--primary);
  background: var(--primary-50);
}

.remedi-mistake-book :deep(.mistake-network-topic-nav select) {
  border-radius: var(--radius-standard);
  color: var(--text);
  background: var(--surface-2);
}

/* 错题讲解侧栏 */
.remedi-mistake-book :deep(.mistake-point-assistant) {
  border-color: var(--border);
  border-radius: var(--radius-panel);
  box-shadow: var(--shadow-md);
}

.remedi-mistake-book :deep(.mistake-point-assistant-head) {
  padding: 16px 18px 13px;
  border-color: var(--border);
  background: var(--surface-2);
}

.remedi-mistake-book :deep(.mistake-point-assistant-head h2) {
  font-size: 16px;
  font-weight: 700;
}

.remedi-mistake-book :deep(.mistake-point-assistant-controls button) {
  border-radius: var(--radius-standard);
}

.remedi-mistake-book :deep(.mistake-point-summary) {
  border-color: var(--border);
  border-radius: var(--radius-surface);
  background: var(--surface-2);
}

.remedi-mistake-book :deep(.mistake-point-summary-toggle) {
  border-color: var(--border);
  border-radius: var(--radius-standard);
  color: var(--text-2);
}

.remedi-mistake-book :deep(.mistake-point-reason) {
  border-color: var(--blue-bg);
  border-radius: var(--radius-standard);
  background: var(--primary-50);
}

.remedi-mistake-book :deep(.mistake-point-chat-title) {
  padding: 14px 18px 8px;
}

.remedi-mistake-book :deep(.mistake-point-empty) {
  border-color: var(--border);
  border-radius: var(--radius-surface);
  background: var(--surface-2);
}

.remedi-mistake-book :deep(.mistake-point-empty-intro strong) {
  color: var(--text);
}

.remedi-mistake-book :deep(.mistake-point-quick-questions button) {
  border-radius: var(--radius-standard);
  color: var(--text-strong);
}

.remedi-mistake-book :deep(.mistake-point-message) {
  border-color: var(--border);
  border-left-color: var(--primary);
  border-radius: var(--radius-surface);
}

.remedi-mistake-book :deep(.mistake-point-message.user) {
  border-color: var(--blue-bg);
  background: var(--primary-50);
}

.remedi-mistake-book :deep(.mistake-point-composer) {
  border-color: var(--border);
}

.remedi-mistake-book :deep(.mistake-point-composer-inner) {
  border-radius: var(--radius-surface);
  background: var(--surface-2);
}

.remedi-mistake-book :deep(.mistake-point-composer-inner:focus-within) {
  border-color: var(--primary);
  background: var(--card);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 12%, transparent);
}

.remedi-mistake-book :deep(.mistake-point-composer button) {
  border-radius: var(--radius-standard);
  background: var(--primary);
}

.remedi-mistake-book :deep(.mistake-point-composer button:hover:not(:disabled)) {
  background: var(--primary-dark);
}

@media (max-width: 960px) {
  .remedi-mistake-book .notebook-filterbar {
    align-items: center;
  }

  .remedi-mistake-book :deep(.sticky-notes-inner) {
    padding: 72px var(--content-frame-gutter-compact) var(--content-frame-gutter-compact);
  }
}

@media (max-width: 760px) {
  .remedi-mistake-book .notebook-filterbar {
    flex-wrap: wrap;
  }
}

@media (max-width: 700px) {
  .remedi-mistake-book .mistake-board-toolbar {
    top: 9px;
    right: 9px;
    left: 9px;
  }

  .remedi-mistake-book .mistake-view-switch {
    max-width: calc(100vw - 80px);
    overflow-x: auto;
  }

  .remedi-mistake-book .mistake-view-switch button {
    min-height: 34px;
    padding: 6px 9px;
    font-size: 11px;
  }

  .remedi-mistake-book .mistake-board-refresh {
    width: 36px;
    height: 36px;
  }

  .remedi-mistake-book .mistake-notebook:not(.is-split) .mistake-notebook-content {
    padding: 66px var(--content-frame-gutter-compact) var(--content-frame-gutter-compact);
  }

  .remedi-mistake-book .notebook-filterbar {
    padding: 10px;
  }

  .remedi-mistake-book .notebook-status-tabs {
    width: 100%;
  }

  .remedi-mistake-book .notebook-status-tabs button {
    flex: 1;
    justify-content: center;
    padding-inline: 6px;
  }

  .remedi-mistake-book .notebook-search-tools {
    width: 100%;
  }

  .remedi-mistake-book .notebook-search {
    min-width: 0;
    flex: 1;
  }

  .remedi-mistake-book .notebook-sort select {
    max-width: 135px;
    padding-inline: 8px 24px;
    font-size: 11px;
  }

  .remedi-mistake-book .notebook-assignment > summary {
    grid-template-columns: 28px minmax(0, 1fr) auto;
    gap: 8px;
    min-height: 0;
    padding: 12px;
  }

  .remedi-mistake-book .notebook-subject-badge {
    grid-column: 2;
    grid-row: 1;
    justify-self: start;
  }

  .remedi-mistake-book .notebook-assignment-title {
    grid-column: 2 / 4;
    grid-row: 2;
  }

  .remedi-mistake-book .notebook-assignment-progress {
    grid-column: 3;
    grid-row: 1;
  }

  .remedi-mistake-book .notebook-assignment-state {
    grid-column: 3;
    grid-row: 2;
    justify-self: end;
  }

  .remedi-mistake-book .notebook-assignment-content {
    padding: 0 10px 12px;
  }

  .remedi-mistake-book .notebook-category {
    padding: 10px;
  }

  .remedi-mistake-book .notebook-assignment-footer {
    align-items: stretch;
  }

  .remedi-mistake-book .notebook-assignment-footer button {
    width: 100%;
  }

  .remedi-mistake-book :deep(.sticky-notes-inner) {
    padding: 66px var(--content-frame-gutter-compact) var(--content-frame-gutter-compact);
  }

  .remedi-mistake-book :deep(.sticky-notes-header h1) {
    font-size: 27px;
  }

  .remedi-mistake-book :deep(.sticky-notes-grid) {
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 220px), 1fr));
    gap: 12px;
  }

  .remedi-mistake-book :deep(.sticky-note) {
    min-height: 190px;
    padding: 18px 16px 15px;
  }

  .remedi-mistake-book :deep(.sticky-assignment) {
    padding: 15px;
  }

  .remedi-mistake-book :deep(.sticky-assignment-questions) {
    grid-template-columns: minmax(0, 1fr);
  }
}

.remedi-mistake-book .mistake-board-toolbar.with-notebook-filters.is-split.is-reversed {
  left: calc(40% + 18px);
}

@media (max-width: 1150px) {
  .remedi-mistake-book .mistake-board-toolbar.with-notebook-filters {
    flex-wrap: wrap;
    justify-content: flex-start;
  }

  .remedi-mistake-book .mistake-board-toolbar.with-notebook-filters .mistake-view-switch {
    margin-left: auto;
  }

  .remedi-mistake-book .mistake-notebook:not(.is-split) .mistake-notebook-content {
    padding-top: 112px;
  }

  .remedi-mistake-book .mistake-notebook.is-split .mistake-notebook-content {
    padding-top: 164px;
  }
}

@media (max-width: 700px) {
  .remedi-mistake-book .mistake-board-toolbar.with-notebook-filters {
    right: 10px;
    left: 10px;
    gap: 8px;
    padding: 8px;
  }

  .remedi-mistake-book .mistake-board-toolbar.with-notebook-filters .mistake-view-switch {
    order: 1;
    max-width: calc(100% - 48px);
    margin-left: 0;
  }

  .remedi-mistake-book .mistake-board-toolbar.with-notebook-filters .mistake-board-refresh {
    display: none;
  }

  .remedi-mistake-book .mistake-board-toolbar.with-notebook-filters .notebook-status-tabs {
    order: 2;
    width: 100%;
  }

  .remedi-mistake-book .mistake-board-toolbar.with-notebook-filters .notebook-search-tools {
    order: 3;
    width: 100%;
  }

  .remedi-mistake-book .mistake-notebook:not(.is-split) .mistake-notebook-content {
    padding-top: 164px;
  }

  .remedi-mistake-book .mistake-notebook.is-split .mistake-notebook-content {
    padding-top: 164px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .remedi-mistake-book .mistake-view-switch button,
  .remedi-mistake-book .notebook-assignment,
  .remedi-mistake-book :deep(.sticky-note),
  .remedi-mistake-book :deep(.sticky-question),
  .remedi-mistake-book :deep(.mistake-point-assistant *) {
    transition: none;
    animation: none;
  }
}
</style>
