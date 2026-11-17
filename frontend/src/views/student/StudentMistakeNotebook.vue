<template>
  <div class="page mistake-map-view remedi-mistake-book">
    <Teleport to=".shell-page-heading.is-mistake-book">
      <div v-if="!assistantFullscreen" class="mistake-view-controls" role="toolbar" aria-label="错题本视图操作">
        <div class="mistake-view-switch" role="group" aria-label="切换错题本样式">
          <button v-for="item in viewOptions" :key="item.key" type="button" :class="{ selected: view === item.key }" :aria-pressed="view === item.key" @click="setView(item.key)"><AppIcon :name="item.icon" :size="15"/>{{ item.label }}</button>
        </div>
        <button class="mistake-board-refresh" type="button" :disabled="loading" aria-label="刷新错题本" title="刷新错题" @click="loadMistakes"><AppIcon name="refresh" :size="17"/></button>
      </div>
    </Teleport>
    <main class="mistakes-panel" :class="`is-${view}`" aria-label="学生错题本">
      <div v-if="removedAssignment" class="mistake-removal-notice" role="status">
        <span>已将「{{ removedAssignment.title }}」的整份错题移出，历史记录仍保留。<em v-if="actionError">{{ actionError }}</em></span>
        <button type="button" :disabled="workingKey === `restore:${removedAssignment.id}`" @click="restoreAssignment">{{ workingKey === `restore:${removedAssignment.id}` ? '恢复中…' : '撤销' }}</button>
        <button type="button" class="mistake-notice-close" aria-label="关闭移出提示" @click="removedAssignment = null"><AppIcon name="x" :size="14"/></button>
      </div>
      <p v-if="loadError" class="mistake-load-error" role="alert">{{ loadError }}</p>

      <MistakeStickyNotes v-else-if="view === 'sticky'" :mistakes="allMistakes" :loading="loading" :split="Boolean(selectedMistake)" :reversed="assistantOnLeft" :fullscreen="assistantFullscreen" :working-key="workingKey" @select-mistake="openAssistant" @study-category="toggleCategoryByPayload" @archive-assignment="archiveById" @start-assignment="router.push('/student/assignments')" @review="openOriginalQuestion($event)">
        <template #assistant><MistakePointAssistant v-if="selectedMistake" :mistake="selectedMistake" :related="relatedMistakes" :progress="assistantProgress" :saving-study="workingKey === assistantStudyKey" :fullscreen="assistantFullscreen" @close="closeAssistant" @swap="assistantOnLeft = !assistantOnLeft" @fullscreen="assistantFullscreen = !assistantFullscreen" @open-original="openOriginalQuestion($event)" @study="toggleAssistantStudy"/></template>
      </MistakeStickyNotes>

      <MistakeRelationshipMap v-else :mode="view" :mistakes="allMistakes" :student-name="studentName" :split="Boolean(selectedMistake)" :reversed="assistantOnLeft" :fullscreen="assistantFullscreen" @select="openAssistant">
        <template #assistant><MistakePointAssistant v-if="selectedMistake" :mistake="selectedMistake" :related="relatedMistakes" :progress="assistantProgress" :saving-study="workingKey === assistantStudyKey" :fullscreen="assistantFullscreen" @close="closeAssistant" @swap="assistantOnLeft = !assistantOnLeft" @fullscreen="assistantFullscreen = !assistantFullscreen" @open-original="openOriginalQuestion($event)" @study="toggleAssistantStudy"/></template>
      </MistakeRelationshipMap>
    </main>
    <PreviousMistakeModal :mistake="selectedOriginalMistake" :other-error-types="originalAssignmentErrorTypes" @close="selectedOriginalMistake = null" @ask-about="askAboutOriginalError" />
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import { useStudentStore } from '../../stores/student'
import type { RelatedMistake, StudentMistake } from '../../api/types'
import PreviousMistakeModal from '../../components/PreviousMistakeModal.vue'
import AppIcon from '../../components/icons/AppIcon.vue'
import type { IconName } from '../../components/icons/paths'
import '../../assets/mistake-book.css'

let mistakePointAssistantPromise: Promise<typeof import('../../components/mistake-book/MistakePointAssistant.vue')> | undefined
function loadMistakePointAssistant() {
  if (!mistakePointAssistantPromise) {
    mistakePointAssistantPromise = import('../../components/mistake-book/MistakePointAssistant.vue').catch((error) => {
      mistakePointAssistantPromise = undefined
      throw error
    })
  }
  return mistakePointAssistantPromise
}
const MistakePointAssistant = defineAsyncComponent(loadMistakePointAssistant)
const MistakeRelationshipMap = defineAsyncComponent(
  () => import('../../components/mistake-book/MistakeRelationshipMap.vue'),
)
const MistakeStickyNotes = defineAsyncComponent(
  () => import('../../components/mistake-book/MistakeStickyNotes.vue'),
)

type NotebookView = 'sticky' | 'mindmap'
interface MistakeCategory { key: string; label: string; itemCount: number; firstItem: StudentMistake | null; items: StudentMistake[]; studentSavedOnly: boolean }
interface AssignmentGroup { id: number; title: string; categories: MistakeCategory[]; ready: boolean; studentSavedOnly: boolean; studyPointCount: number; studiedStudyPointCount: number }
interface MistakeQuestionGroup {
  questionId: number | null
  items: StudentMistake[]
  representative: StudentMistake
  studied: boolean
}
interface OriginalAssignmentErrorType {
  key: string
  label: string
  itemCount: number
  representative: StudentMistake
}
type RelatedMistakeIndex = Map<string, Map<string, Map<string, StudentMistake[]>>>
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
const view = ref<NotebookView>('sticky')
const selectedOriginalMistake = ref<RelatedMistake | StudentMistake | null>(null)
const originalAssignmentErrorTypes = computed<OriginalAssignmentErrorType[]>(() => {
  const selected = selectedOriginalMistake.value
  if (!selected) return []
  const assignment = notebookData.value.assignmentGroupsById.get(selected.assignment_id)
  if (!assignment) return []

  const selectedMistakeRecord = allMistakes.value.find((item) => item.id === selected.id && item.assignment_id === selected.assignment_id)
  const selectedCategoryLabel = selectedMistakeRecord?.category_label
    ?? ('category_label' in selected ? selected.category_label : '')
  const selectedCategoryKey = selectedCategoryLabel ? normalizeNotebookCategory(selectedCategoryLabel) : ''
  const categoriesByLabel = new Map<string, OriginalAssignmentErrorType>()
  for (const category of assignment.categories) {
    const labelKey = normalizeNotebookCategory(category.label)
    if (labelKey === selectedCategoryKey || category.studentSavedOnly || !category.firstItem) continue
    const label = category.label || category.firstItem.error_type
    const existing = categoriesByLabel.get(labelKey)
    if (existing) existing.itemCount += category.itemCount
    else categoriesByLabel.set(labelKey, {
      key: category.key,
      label,
      itemCount: category.itemCount,
      representative: category.firstItem,
    })
  }
  return Array.from(categoriesByLabel.values()).sort((left, right) => left.label.localeCompare(right.label, 'zh-CN'))
})
const selectedMistake = ref<StudentMistake | null>(null)
const workingKey = ref('')
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
  { key: 'sticky', label: '便利贴', icon: 'file' },
  { key: 'mindmap', label: '思维导图', icon: 'chart' },
]
const relatedMistakeIndexCache = new WeakMap<StudentMistake[], RelatedMistakeIndex>()
const notebookData = computed(() => buildNotebookData(allMistakes.value))
const assignmentGroups = computed(() => notebookData.value.assignmentGroups)
const relatedMistakes = computed(() => {
  const mistake = selectedMistake.value
  if (!mistake) return []
  return getRelatedMistakeIndex(allMistakes.value)
    .get(mistake.question_subject)?.get(mistake.knowledge_point)?.get(mistake.category_key) ?? []
})
const assistantAssignment = computed(() => selectedMistake.value ? notebookData.value.assignmentGroupsById.get(selectedMistake.value.assignment_id) : undefined)
const assistantProgress = computed(() => ({ completed: assistantAssignment.value?.studiedStudyPointCount ?? 0, total: assistantAssignment.value?.studyPointCount ?? 0, complete: Boolean(assistantAssignment.value?.ready) }))
const assistantStudyKey = computed(() => selectedMistake.value
  ? `question:${studyKey(selectedMistake.value.assignment_id, selectedMistake.value.category_key)}:${selectedMistake.value.question_id}`
  : '')

function questionStudyKey(assignmentId: number, question: MistakeQuestionGroup): string {
  return `question:${studyKey(assignmentId, question.representative.category_key)}:${question.questionId ?? question.representative.id}`
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

function buildQuestionGroups(items: StudentMistake[]): MistakeQuestionGroup[] {
  const groups = new Map<string, MistakeQuestionGroup>()
  for (const item of items) {
    const questionId = isStudentSaved(item) ? null : item.question_id
    const key = isStudentSaved(item) ? `saved:${item.id}` : `submission:${item.submission_id}`
    let group = groups.get(key)
    if (!group) {
      group = { questionId, items: [], representative: item, studied: true }
      groups.set(key, group)
    }
    group.items.push(item)
  }
  return Array.from(groups.values()).map((group) => {
    group.items.sort((left, right) => right.created_at.localeCompare(left.created_at) || right.id - left.id)
    group.representative = group.items[0]
    group.studied = group.items.every((item) => item.question_studied ?? item.category_studied)
    return group
  })
}

function normalizeNotebookCategory(value: string): string {
  return value.trim().toLocaleLowerCase() || '待归类'
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
        categories: [],
        ready: false,
        studentSavedOnly: true,
        studyPointCount: 0,
        studiedStudyPointCount: 0,
      }
      groups.set(item.assignment_id, group)
      categoriesByAssignment.set(item.assignment_id, new Map())
    }
    group.studentSavedOnly = group.studentSavedOnly && isStudentSaved(item)
    const categories = item.error_categories?.length
      ? item.error_categories
      : [{ key: item.category_key, label: item.category_label || item.error_type, category_studied: item.category_studied, question_studied: item.question_studied }]
    for (const itemCategory of categories) {
      const categoryIndex = categoriesByAssignment.get(item.assignment_id)!
      let category = categoryIndex.get(itemCategory.key)
      if (!category) {
        category = {
          key: itemCategory.key,
          label: itemCategory.label || item.error_type,
          itemCount: 0,
          firstItem: null,
          items: [],
          studentSavedOnly: true,
        }
        categoryIndex.set(itemCategory.key, category)
        group.categories.push(category)
      }
      const categoryItem: StudentMistake = {
        ...item,
        category_key: itemCategory.key,
        category_label: itemCategory.label,
        category_studied: itemCategory.category_studied ?? item.category_studied,
        question_studied: itemCategory.question_studied ?? item.question_studied,
      }
      category.itemCount += 1
      category.items.push(categoryItem)
      if (!category.firstItem) category.firstItem = categoryItem
      category.studentSavedOnly = category.studentSavedOnly && isStudentSaved(item)
    }
  }

  const assignmentGroups = Array.from(groups.values()).map((group) => {
    const questionStudyBySubmission = new Map<number, boolean>()
    for (const category of group.categories) {
      for (const question of buildQuestionGroups(category.items)) {
        if (isStudentSaved(question.representative)) continue
        const submissionId = question.representative.submission_id
        questionStudyBySubmission.set(
          submissionId,
          (questionStudyBySubmission.get(submissionId) ?? true) && question.studied,
        )
      }
    }
    group.studyPointCount = questionStudyBySubmission.size
    group.studiedStudyPointCount = Array.from(questionStudyBySubmission.values()).filter(Boolean).length
    group.ready = group.studentSavedOnly || (group.studyPointCount > 0 && group.studiedStudyPointCount === group.studyPointCount)
    return group
  })
  return {
    assignmentGroups,
    assignmentGroupsById: groups,
  }
}
function isStudentSaved(item: StudentMistake) { return item.source_kind === 'student_saved' }
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
    student.setMistakePageTitle(next === 'sticky' ? '错题便利贴' : '')
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
function askAboutOriginalError(mistake: StudentMistake) {
  selectedOriginalMistake.value = null
  openAssistant(mistake)
}
async function loadMistakes(): Promise<boolean> {
  loading.value = true
  loadError.value = ''
  actionError.value = ''
  try {
    allMistakes.value = await student.fetchMyMistakes(false)
    mistakesLoaded.value = true
    if (selectedMistake.value) {
      const previous = selectedMistake.value
      const refreshed = allMistakes.value.find((item) => item.id === previous.id)
      const category = refreshed?.error_categories.find((item) => item.key === previous.category_key)
      selectedMistake.value = refreshed
        ? category
          ? {
              ...refreshed,
              category_key: category.key,
              category_label: category.label,
              category_studied: category.category_studied ?? refreshed.category_studied,
              question_studied: category.question_studied ?? refreshed.question_studied,
            }
          : refreshed
        : null
    }
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
async function toggleQuestionStudy(assignmentId: number, question: MistakeQuestionGroup) {
  if (workingKey.value || question.questionId === null || isStudentSaved(question.representative)) return
  const studied = !question.studied
  workingKey.value = questionStudyKey(assignmentId, question)
  actionError.value = ''
  try {
    await student.setMistakeQuestionStudied({
      assignment_id: assignmentId,
      question_id: question.questionId,
      category_key: question.representative.category_key,
      studied,
    })
    for (const item of question.items) item.question_studied = studied
    updateCategoryStudyState(assignmentId, question.questionId, question.representative.category_key, { question_studied: studied })
    notifyMistakeReviewChanged(allMistakes.value)
  } catch {
    actionError.value = '这道题的学习状态保存失败，请稍后重试。'
  } finally { workingKey.value = '' }
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
      item.question_studied = payload.studied
    }
    for (const item of category?.items ?? []) {
      updateCategoryStudyState(payload.assignment_id, item.question_id, payload.category_key, {
        category_studied: payload.studied,
        question_studied: payload.studied,
      })
    }
    notifyMistakeReviewChanged(allMistakes.value)
  } catch {
    actionError.value = '学习状态保存失败，请稍后重试。'
  } finally { workingKey.value = '' }
}
function updateCategoryStudyState(
  assignmentId: number,
  questionId: number | null,
  categoryKey: string,
  state: { category_studied?: boolean; question_studied?: boolean },
) {
  for (const mistake of allMistakes.value) {
    if (mistake.assignment_id !== assignmentId || (questionId !== null && mistake.question_id !== questionId)) continue
    for (const category of mistake.error_categories ?? []) {
      if (category.key !== categoryKey) continue
      if (state.category_studied !== undefined) category.category_studied = state.category_studied
      if (state.question_studied !== undefined) category.question_studied = state.question_studied
    }
    for (const detail of mistake.error_details ?? []) {
      if (detail.category_key !== categoryKey) continue
      if (state.category_studied !== undefined) detail.category_studied = state.category_studied
      if (state.question_studied !== undefined) detail.question_studied = state.question_studied
    }
    if (mistake.category_key === categoryKey) {
      if (state.category_studied !== undefined) mistake.category_studied = state.category_studied
      if (state.question_studied !== undefined) mistake.question_studied = state.question_studied
    }
  }
  const selected = selectedMistake.value
  if (selected?.assignment_id === assignmentId && selected.category_key === categoryKey
    && (questionId === null || selected.question_id === questionId)) {
    if (state.category_studied !== undefined) selected.category_studied = state.category_studied
    if (state.question_studied !== undefined) selected.question_studied = state.question_studied
  }
}
async function toggleAssistantStudy() {
  const mistake = selectedMistake.value
  if (!mistake || isStudentSaved(mistake)) return
  const item = allMistakes.value.find((candidate) => candidate.submission_id === mistake.submission_id)
  if (!item) return
  const category = item.error_categories.find((entry) => entry.key === mistake.category_key)
  const scopedItem = category ? {
    ...item,
    category_key: category.key,
    category_label: category.label,
    category_studied: category.category_studied ?? item.category_studied,
    question_studied: category.question_studied ?? item.question_studied,
  } : item
  const question = buildQuestionGroups([scopedItem])[0]
  if (question) await toggleQuestionStudy(mistake.assignment_id, question)
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
    openAssistant(mistake)
  }
  const query = { ...route.query }
  delete query.review
  void router.replace({ path: route.path, query })
}

watch(() => route.query.review, openRequestedReview)

onMounted(() => {
  void loadMistakes().finally(() => {
    // 错题加载完成后预热聊天组件，避免第一次打开右侧问答时等待异步代码块。
    void loadMistakePointAssistant().catch(() => undefined)
  })
})
onBeforeUnmount(() => {
  viewRequestId++
  student.setMistakePageTitle('')
})
</script>

<style scoped>
.remedi-mistake-book { display: flex; min-height: 0; flex: 1 1 0; flex-direction: column; overflow: hidden; }
.remedi-mistake-book .mistakes-panel { position: relative; width: 100%; height: auto; min-height: 0; flex: 1 1 0%; overflow: hidden; }
.remedi-mistake-book .mistake-board-toolbar { position: static; z-index: 10; }
.remedi-mistake-book .mistake-view-controls {
  position: static;
  z-index: auto;
  display: flex;
  min-height: 50px;
  flex: 0 0 auto;
  align-items: center;
  gap: 12px;
}
.remedi-mistake-book .mistake-view-controls .mistake-view-switch {
  flex: 0 0 auto;
}
.remedi-mistake-book .mistake-map-viewport-frame, .remedi-mistake-book .mistake-network-frame { height: 100%; min-height: 0; }
.remedi-mistake-book .mistake-map-viewport, .remedi-mistake-book .mistake-network-viewport { height: 100%; min-height: 0; }
.remedi-mistake-book .mistake-network-topic-nav { top: 62px; }
/* Each question is one compact row: prompt on the left, individual learn/review actions on the right. */
.remedi-mistake-book .mistake-load-error { margin: 10px 0; color: var(--red-strong); font-size: 12px; }
.remedi-mistake-book .mistake-point-assistant { animation: mistake-assistant-enter .22s ease-out both; }
@keyframes mistake-assistant-enter { from { opacity: 0; transform: translateX(8px); } to { opacity: 1; transform: translateX(0); } }
@media (max-width: 700px) {
  .remedi-mistake-book .mistake-view-controls { gap: 0; }
  .remedi-mistake-book .mistake-view-switch { max-width: calc(100vw - 72px); overflow-x: auto; }
  .remedi-mistake-book .mistake-view-switch button { min-width: auto; padding-inline: 9px; }
  .remedi-mistake-book .mistake-board-refresh { display: none; }
}

/* 错题本统一视觉：保持各视图的数据和交互，只调整层级、留白与表面样式。 */
.remedi-mistake-book .mistakes-panel {
  padding: 16px 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  background: var(--card);
  box-shadow: var(--shadow);
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

/* 便利贴扩展列表 */

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

:deep(.sticky-list-more:hover) {
  border-color: var(--primary);
  background: var(--primary-50);
}

/* 便利贴视图：保留科目色彩，用规整卡片替代旋转纸片和装饰胶带。 */
.remedi-mistake-book :deep(.mistake-sticky-notes) {
  height: 100%;
  min-height: 0;
}

.remedi-mistake-book :deep(.mistake-sticky-notes:not(.is-split) .sticky-notes-inner) {
  max-width: none;
  padding: 16px 0 0;
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

  .remedi-mistake-book :deep(.mistake-sticky-notes:not(.is-split) .sticky-notes-inner) {
    padding-top: 16px;
  }
}

@media (max-width: 700px) {
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

  .remedi-mistake-book :deep(.mistake-sticky-notes:not(.is-split) .sticky-notes-inner) {
    padding-top: 16px;
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

@media (prefers-reduced-motion: reduce) {
  .remedi-mistake-book .mistake-view-switch button, .remedi-mistake-book :deep(.sticky-note), .remedi-mistake-book :deep(.sticky-question), .remedi-mistake-book :deep(.mistake-point-assistant *) {
    transition: none;
    animation: none;
  }
}

/* 错题本保持视口内滚动；窄屏由整页自然滚动。 */

/* 便利贴保留页面留白，思维导图画布延伸到视口底部。 */
.remedi-mistake-book .mistakes-panel.is-sticky {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 0 0 16px;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.remedi-mistake-book:has(> .mistakes-panel.is-mindmap) {
  flex: 1 1 0%;
  min-height: 0;
  padding-bottom: 0;
}

.remedi-mistake-book .mistakes-panel.is-mindmap {
  display: flex;
  flex: 1 1 0%;
  flex-direction: column;
  gap: 0;
  min-height: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.remedi-mistake-book .mistakes-panel.is-sticky > .mistake-sticky-notes,
.remedi-mistake-book .mistakes-panel.is-mindmap > :deep(.mistake-map-section) {
  flex: 1 1 0%;
  width: 100%;
  height: auto;
  min-width: 0;
  min-height: 0;
}

.remedi-mistake-book .mistakes-panel.is-sticky > .mistake-sticky-notes {
  min-height: 0;
}

.remedi-mistake-book .mistakes-panel.is-sticky > :deep(.mistake-sticky-notes.is-split:not(.is-reversed) > .mistake-point-assistant),
.remedi-mistake-book .mistakes-panel.is-mindmap > :deep(.mistake-map-section.is-split:not(.is-reversed) > .mistake-point-assistant) {
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
}

.remedi-mistake-book :deep(.mistake-map-viewport) {
  border: 0 !important;
  border-radius: 0;
  background: transparent !important;
  box-shadow: none !important;
}

.remedi-mistake-book :deep(.mistake-board-empty) {
  height: 100%;
  min-height: 0;
  border: 0;
  border-radius: 0;
  background: transparent !important;
  box-shadow: none;
}

@media (max-width: 760px) {
  .remedi-mistake-book .mistake-view-controls {
    min-height: 42px;
  }

  .remedi-mistake-book .mistakes-panel.is-sticky {
    padding: 0 0 12px;
  }

  .remedi-mistake-book .mistakes-panel.is-mindmap {
    padding: 0;
  }

}

/* 搜索与排序控件使用同一组中性色，焦点时只显示一层品牌色提示。 */

</style>
