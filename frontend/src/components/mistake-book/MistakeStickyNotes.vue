<template>
  <section
    class="mistake-sticky-notes"
    :class="{ 'is-split': split, 'is-reversed': reversed, 'is-assistant-fullscreen': fullscreen }"
    aria-label="便利贴错题本"
    :aria-busy="loading"
  >
    <div class="sticky-notes-inner">
      <header class="sticky-notes-header">
        <div class="sticky-notes-kicker"><span aria-hidden="true">✳</span>{{ studentName ? `${studentName} · 学习记录` : '把错因贴在眼前' }}</div>
        <h1>{{ selectedCategory ? selectedCategory.label : selectedSubject ? displaySubject(selectedSubject.key) : '错题便利贴' }}</h1>
        <p>{{ screen === 'subjects' ? '选一个科目，从最需要复习的错误类别开始。' : screen === 'categories' ? '每张便利贴是一类错误；同类错题会放在一起。' : `${selectedCategory!.entries.length} 道错题，来自 ${selectedCategory!.assignmentCount} 份作业。` }}</p>
      </header>

      <nav v-if="screen !== 'subjects'" class="sticky-notes-breadcrumb" aria-label="便利贴层级">
        <button type="button" @click="goToSubjects">全部科目</button><span aria-hidden="true">/</span>
        <template v-if="screen === 'detail'"><button type="button" @click="goToCategories">{{ displaySubject(selectedSubject!.key) }}</button><span aria-hidden="true">/</span><span aria-current="page">{{ selectedCategory!.label }}</span></template>
        <span v-else aria-current="page">{{ displaySubject(selectedSubject!.key) }}</span>
      </nav>

      <div v-if="loading" class="sticky-notes-grid" aria-hidden="true">
        <div v-for="index in 4" :key="index" class="sticky-note sticky-note-skeleton" :style="noteStyle(index)" />
      </div>
      <div v-else-if="!mistakes.length" class="sticky-notes-empty">
        <div class="sticky-notes-empty-icon">✳</div>
        <h2>第一张便利贴，等你来写</h2>
        <p>完成一份作业诊断后，错题会按科目和错误类别整理在这里。</p>
        <button type="button" @click="$emit('start-assignment')">去作业列表 <span aria-hidden="true">↗</span></button>
      </div>
      <div v-else-if="screen === 'subjects'" class="sticky-notes-grid" aria-label="科目便利贴">
        <button v-for="(subject, index) in subjects" :key="subject.key" type="button" class="sticky-note" :class="`sticky-note-${noteColors[subject.key] || 'lilac'}`" :style="noteStyle(index)" @click="selectSubject(subject.key)">
          <span class="sticky-note-index">科目 {{ String(index + 1).padStart(2, '0') }}</span>
          <strong class="sticky-note-title">{{ displaySubject(subject.key) }}</strong>
          <span class="sticky-note-rule" />
          <span class="sticky-note-stat"><b>{{ subject.categories.length }}</b> 类错误 · <b>{{ subject.entries.length }}</b> 道错题</span>
          <span class="sticky-note-foot"><span>{{ subject.categories.filter((category) => !category.studied).length ? `还有 ${subject.categories.filter((category) => !category.studied).length} 类待学习` : '全部类别已学完' }}</span><span aria-hidden="true">↗</span></span>
        </button>
      </div>
      <div v-else-if="screen === 'categories'" class="sticky-notes-grid" aria-label="错误类别便利贴">
        <button v-for="(category, index) in selectedSubject!.categories" :key="category.key" type="button" class="sticky-note" :class="[`sticky-note-${categoryColors[index % categoryColors.length]}`, { 'is-studied': category.studied }]" :style="noteStyle(index)" @click="openCategory(category)">
          <span class="sticky-note-index">错误类别 {{ String(index + 1).padStart(2, '0') }}</span>
          <strong class="sticky-note-title">{{ category.label }}</strong>
          <span class="sticky-note-rule" />
          <span class="sticky-note-stat"><b>{{ category.entries.length }}</b> 道错题 · <b>{{ category.assignmentCount }}</b> 份作业</span>
          <span v-if="category.tags.length" class="sticky-note-tags">{{ category.tags.join(' · ') }}</span>
          <span class="sticky-note-foot"><span>{{ category.studied ? '已学完' : category.assignmentCount > 1 ? '在多份作业中出现' : '继续复习' }}</span><span aria-hidden="true">↗</span></span>
        </button>
      </div>
      <div v-else class="sticky-notes-detail" :aria-label="`${selectedCategory!.label}错题`">
        <div class="sticky-detail-summary"><span>这类错误的作业记录</span><strong>{{ assignments.filter((assignment) => assignment.studied).length }}<small> / {{ assignments.length }} 份已学完</small></strong></div>
        <div class="sticky-assignment-list">
          <article v-for="(assignment, assignmentIndex) in assignments" :key="`${assignment.assignmentId}:${assignment.categoryKey}`" class="sticky-assignment" :class="[`sticky-note-${categoryColors[assignmentIndex % categoryColors.length]}`, { 'is-studied': assignment.studied }]">
            <div class="sticky-assignment-head">
              <div><span class="sticky-assignment-date">{{ formatDate(assignment.entries[0].assignment_created_at) }}</span><h2>{{ assignment.title }}</h2><p>{{ assignment.entries.every((entry) => entry.source_kind === 'student_saved') ? '你主动收录的复习题目' : `${assignment.entries.length} 道这类错题 · 本份作业已学 ${progressFor(assignment.assignmentId).completed}/${progressFor(assignment.assignmentId).total} 类错误` }}</p></div>
              <span class="sticky-assignment-state">{{ assignment.studied ? '此类已学完' : '待学习' }}</span>
            </div>
            <div class="sticky-assignment-questions">
              <article v-for="(entry, entryIndex) in assignment.entries" :key="entry.id" class="sticky-question" :class="[`sticky-note-${categoryColors[(assignmentIndex + entryIndex + 1) % categoryColors.length]}`, { 'is-current': focusedMistakeId === entry.id }]" :style="noteStyle(entryIndex)" @click="selectQuestion(entry)">
                <div class="sticky-question-main" role="button" tabindex="0" :aria-pressed="focusedMistakeId === entry.id" :aria-label="entry.source_kind === 'student_saved' ? '查看自主收录题目' : `查看第 ${entry.question_order} 题错题详情`" title="单击查看题目详情" @keydown.enter.prevent="selectQuestion(entry)" @keydown.space.prevent="selectQuestion(entry)">
                  <div class="sticky-question-head"><strong>{{ entry.source_kind === 'student_saved' ? '自主收录题目' : `第 ${entry.question_order} 题${entry.step_seq ? ` · 第 ${entry.step_seq} 步` : ''}` }}</strong><span>{{ entry.knowledge_point }}</span></div>
                  <p class="sticky-question-excerpt">{{ entry.question_stem }}</p>
                  <p class="sticky-question-diagnosis">{{ entry.detail || entry.error_type }}</p>
                </div>
                <div class="sticky-question-actions"><button type="button" @click.stop="selectQuestion(entry)">{{ entry.source_kind === 'student_saved' ? '继续复习' : '查看错题讲解' }} <span aria-hidden="true">↗</span></button><button v-if="entry.source_kind !== 'student_saved'" type="button" @click.stop="$emit('review', entry)">查看原题 <span aria-hidden="true">↗</span></button></div>
              </article>
            </div>
            <div class="sticky-assignment-actions">
              <button v-if="assignment.entries.some((entry) => entry.source_kind !== 'student_saved')" type="button" class="sticky-study-button" :disabled="Boolean(workingKey)" @click="toggleStudied(assignment)">{{ workingKey === studyKey(assignment) ? '保存中…' : assignment.studied ? '取消已学会' : '学完这类错误' }}</button>
              <span>{{ assignment.entries.every((entry) => entry.source_kind === 'student_saved') ? '这是你主动收录的题目' : progressFor(assignment.assignmentId).complete ? '这份作业的错误类别已全部学完' : `还有 ${progressFor(assignment.assignmentId).total - progressFor(assignment.assignmentId).completed} 类待学习` }}</span>
              <button type="button" class="sticky-archive-button" :disabled="!progressFor(assignment.assignmentId).complete || Boolean(workingKey)" @click="$emit('archive-assignment', assignment.assignmentId)">{{ workingKey === `archive:${assignment.assignmentId}` ? '正在移出…' : '整份作业移出错题本' }}</button>
            </div>
          </article>
        </div>
      </div>
    </div>
    <slot name="assistant" />
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { StudentMistake } from '../../api/types'

type Category = { key: string; label: string; entries: StudentMistake[]; studied: boolean; assignmentCount: number; tags: string[] }
type SubjectGroup = { key: string; categories: Category[]; entries: StudentMistake[] }
type StickyAssignment = { assignmentId: number; categoryKey: string; entries: StudentMistake[]; studied: boolean; title: string }

const props = defineProps<{
  mistakes: StudentMistake[]
  loading: boolean
  studentName?: string
  split?: boolean
  reversed?: boolean
  fullscreen?: boolean
  workingKey?: string
}>()
const emit = defineEmits<{
  'select-mistake': [mistake: StudentMistake]
  'study-category': [payload: { assignment_id: number; category_key: string; studied: boolean }]
  'archive-assignment': [assignmentId: number]
  'start-assignment': []
  review: [mistake: StudentMistake]
}>()

const selectedSubjectKey = ref<string | null>(null)
const selectedCategoryKey = ref<string | null>(null)
const focusedMistakeId = ref<number | null>(null)
const noteColors: Record<string, string> = { math: 'yellow', english: 'pink', english_exercise: 'peach', physics: 'blue', chemistry: 'lilac', biology: 'mint', history: 'peach', geography: 'blue', chinese: 'pink', politics: 'yellow', computer_science: 'mint', other: 'lilac' }
const categoryColors = ['yellow', 'mint', 'pink', 'blue', 'peach', 'lilac']

const subjects = computed<SubjectGroup[]>(() => {
  const groups = new Map<string, SubjectGroup>()
  for (const entry of props.mistakes) {
    const key = entry.question_subject === 'english_exercise' ? 'english' : entry.question_subject || 'other'
    const subject = groups.get(key) ?? { key, entries: [], categories: [] }
    subject.entries.push(entry)
    let category = subject.categories.find((item) => item.key === entry.category_key)
    if (!category) {
      category = { key: entry.category_key, label: entry.category_label || entry.error_type, entries: [], studied: true, assignmentCount: 0, tags: [] }
      subject.categories.push(category)
    }
    category.entries.push(entry)
    category.studied = category.studied && entry.category_studied
    groups.set(key, subject)
  }
  for (const subject of groups.values()) {
    for (const category of subject.categories) {
      category.entries.sort((a, b) => b.assignment_created_at.localeCompare(a.assignment_created_at))
      category.assignmentCount = new Set(category.entries.map((item) => item.assignment_id)).size
      category.tags = Array.from(new Set(category.entries.map((item) => item.knowledge_point).filter(Boolean))).slice(0, 2)
    }
    subject.categories.sort((a, b) => Number(a.studied) - Number(b.studied) || b.entries.length - a.entries.length || a.label.localeCompare(b.label, 'zh-CN'))
  }
  return Array.from(groups.values()).sort((a, b) => a.key.localeCompare(b.key, 'zh-CN'))
})
const selectedSubject = computed(() => subjects.value.find((item) => item.key === selectedSubjectKey.value))
const selectedCategory = computed(() => selectedSubject.value?.categories.find((item) => item.key === selectedCategoryKey.value))
const screen = computed(() => selectedCategory.value ? 'detail' : selectedSubject.value ? 'categories' : 'subjects')
const assignments = computed<StickyAssignment[]>(() => {
  if (!selectedCategory.value) return []
  const grouped = new Map<number, StickyAssignment>()
  for (const entry of selectedCategory.value.entries) {
    const group = grouped.get(entry.assignment_id) ?? { assignmentId: entry.assignment_id, categoryKey: entry.category_key, entries: [], studied: true, title: entry.assignment_title }
    group.entries.push(entry)
    group.studied = group.studied && entry.category_studied
    grouped.set(entry.assignment_id, group)
  }
  return Array.from(grouped.values()).map((group) => ({ ...group, entries: group.entries.sort((a, b) => a.question_order - b.question_order) })).sort((a, b) => b.entries[0].assignment_created_at.localeCompare(a.entries[0].assignment_created_at))
})

watch(() => props.mistakes.map((item) => item.id).join(','), () => {
  if (selectedSubjectKey.value && !subjects.value.some((item) => item.key === selectedSubjectKey.value)) goToSubjects()
  else if (selectedCategoryKey.value && !selectedSubject.value?.categories.some((item) => item.key === selectedCategoryKey.value)) goToCategories()
})

function displaySubject(value: string) {
  const labels: Record<string, string> = { math: '数学', english: '英语', physics: '物理', chemistry: '化学', biology: '生物', chinese: '语文', history: '历史', geography: '地理', politics: '道德与法治', computer_science: '信息科技' }
  return labels[value] || value || '其他学科'
}
function formatDate(value?: string) {
  const date = new Date(value || '')
  return Number.isNaN(date.getTime()) ? '日期未记录' : date.toLocaleDateString('zh-CN', { year: 'numeric', month: 'numeric', day: 'numeric' })
}
function noteStyle(index: number) { return { '--sticky-tilt': `${[-1.8, 1.3, -.7, 1.7, -.9, 1.1][index % 6]}deg` } }
function selectSubject(key: string) { selectedSubjectKey.value = key; selectedCategoryKey.value = null }
function openCategory(category: Category) { selectedCategoryKey.value = category.key }
function goToSubjects() { selectedSubjectKey.value = null; selectedCategoryKey.value = null }
function goToCategories() { selectedCategoryKey.value = null }
function selectQuestion(entry: StudentMistake) { focusedMistakeId.value = entry.id; emit('select-mistake', entry) }
function studyKey(assignment: StickyAssignment) { return `study:${assignment.assignmentId}:${assignment.categoryKey}` }
function progressFor(assignmentId: number) {
  const items = props.mistakes.filter((item) => item.assignment_id === assignmentId)
  const categories = new Map<string, boolean>()
  for (const item of items) categories.set(item.category_key, (categories.get(item.category_key) ?? true) && item.category_studied)
  const completed = Array.from(categories.values()).filter(Boolean).length
  return { completed, total: categories.size, complete: categories.size > 0 && completed === categories.size }
}
function toggleStudied(assignment: StickyAssignment) {
  emit('study-category', { assignment_id: assignment.assignmentId, category_key: assignment.categoryKey, studied: !assignment.studied })
}
</script>

<style scoped>
.sticky-question-diagnosis { display: -webkit-box; max-height: 40px; margin-top: 7px; overflow: hidden; color: inherit; opacity: .72; font-size: 11px; line-height: 1.5; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.sticky-assignment-questions > article { min-width: 0; }
</style>
