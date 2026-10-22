<template>
  <div class="page">
    <div class="page-head">
      <h2>{{ subjectLabel }} Agent 知识库</h2>
      <p class="page-sub">添加教材、讲义或评分标准，让本学科老师回答时参考相关资料，并注明来源。</p>
    </div>

    <div v-if="!subject" class="card empty">教师登录时需要先选择任教学科。</div>
    <template v-else>
      <div class="feedback" aria-live="polite">
        <p v-if="error" class="error-msg" role="alert">{{ error }}</p>
        <p v-if="notice" class="notice">{{ notice }}</p>
        <p v-for="warning in warnings" :key="warning" class="warning">{{ warning }}</p>
      </div>

      <div class="card">
        <h3>添加教学资料</h3>
        <div class="entry-modes" role="group" aria-label="资料添加方式">
          <button type="button" :class="{ selected: entryMode === 'text' }" :aria-pressed="entryMode === 'text'" :disabled="mutating" @click="entryMode = 'text'">粘贴文字</button>
          <button type="button" :class="{ selected: entryMode === 'pdf' }" :aria-pressed="entryMode === 'pdf'" :disabled="mutating" @click="entryMode = 'pdf'">导入 PDF</button>
        </div>
        <div v-if="entryMode === 'pdf'" class="form-row">
          <label for="knowledge-pdf">选择 PDF</label>
          <input id="knowledge-pdf" ref="fileInput" type="file" accept=".pdf,application/pdf" :disabled="mutating" @change="selectPdf" />
          <span class="hint">最大 10 MB，支持可复制文字的 PDF。扫描件请先识别为文字后再导入。</span>
          <span v-if="pdfFile" class="file-name">{{ pdfFile.name }}</span>
        </div>
        <div class="form-row">
          <label for="knowledge-title">资料标题{{ entryMode === 'pdf' ? '（选填，默认使用文件名）' : '' }}</label>
          <input id="knowledge-title" v-model="title" maxlength="160" :disabled="mutating" placeholder="例如：一次函数图像与性质" />
        </div>
        <div class="form-row">
          <label for="knowledge-source">来源（选填）</label>
          <input id="knowledge-source" v-model="sourceName" maxlength="200" :disabled="mutating" placeholder="例如：七年级下册教材 / 第三章讲义" />
        </div>
        <div v-if="entryMode === 'text'" class="form-row">
          <label for="knowledge-content">资料内容</label>
          <textarea id="knowledge-content" v-model="content" rows="8" maxlength="20000" :disabled="mutating" placeholder="粘贴知识要点、例题解析或评分标准。资料只用于当前学科的答疑。" />
          <span class="hint">{{ content.length }} / 20000 字</span>
        </div>
        <button v-if="entryMode === 'text'" class="btn" :disabled="mutating || !title.trim() || !content.trim()" @click="save">
          {{ saving ? '正在保存…' : `加入${subjectLabel}知识库` }}
        </button>
        <button v-else class="btn" :disabled="mutating || !pdfFile" @click="importPdf">
          {{ importing ? '正在导入并处理资料…' : `导入${subjectLabel}知识库` }}
        </button>
      </div>

      <div class="card">
        <h3>试查资料</h3>
        <p class="section-hint">输入学生可能提出的问题，检查老师会参考哪些内容。</p>
        <form class="search-form" @submit.prevent="search">
          <label class="sr-only" for="knowledge-query">试查问题</label>
          <input id="knowledge-query" v-model="query" maxlength="1000" placeholder="例如：一次函数的图像如何判断增减性？" :disabled="searching" />
          <button class="btn" type="submit" :disabled="searching || mutating || !query.trim()">{{ searching ? '正在检索…' : '检索' }}</button>
        </form>
        <template v-if="searchResult">
          <p class="result-summary">{{ searchResult.retrieval_mode === 'hybrid' ? '混合检索' : '关键词检索' }} · 找到 {{ searchResult.items.length }} 条相关资料</p>
          <p v-for="warning in searchResult.warnings" :key="warning" class="warning">{{ warning }}</p>
          <div v-if="!searchResult.items.length" class="empty">没有检索到直接相关的资料，可以补充教学资料或换一个问题。</div>
          <article v-for="result in searchResult.items" :key="`${result.document_id}-${result.passage_id}`" class="search-result">
            <div class="result-head"><b>{{ result.title }}</b><span class="citation">{{ result.citation }}</span></div>
            <p class="source">来源：{{ result.source_name || '教师整理' }}<span v-if="result.page_number"> · 第 {{ result.page_number }} 页</span></p>
            <p class="passage">{{ result.content }}</p>
          </article>
        </template>
      </div>

      <div class="card">
        <div class="knowledge-head">
          <h3>{{ subjectLabel }}资料 <span class="count">{{ items.length }}</span></h3>
          <div class="head-actions">
            <button class="btn ghost small" :disabled="loading || mutating" @click="load()">刷新</button>
            <button class="btn ghost small" :disabled="loading || mutating || !vectorEnabled || !items.length" @click="reindex">{{ reindexing ? '正在更新索引…' : '重建检索索引' }}</button>
          </div>
        </div>
        <p v-if="!loading" class="section-hint">{{ vectorEnabled ? '已配置向量检索。首次连接或更换向量库后，请重建检索索引。' : '关键词检索可用；连接向量库后可重建索引。' }}</p>
        <div v-if="loading" class="loading">加载中…</div>
        <div v-else-if="!items.length" class="empty">这个学科的知识库目前为空。</div>
        <article v-for="item in items" :key="item.id" class="knowledge-item">
          <header>
            <div><b>{{ item.title }}</b><small>来源：{{ item.source_name || '教师整理' }}<span v-if="item.passage_count"> · {{ item.passage_count }} 个检索片段</span></small></div>
            <button class="btn danger-outline small" :disabled="mutating" @click="remove(item)">{{ deletingId === item.id ? '正在删除…' : '删除' }}</button>
          </header>
          <p v-if="item.content.length <= 600" class="passage">{{ item.content }}</p>
          <template v-else>
            <p class="passage">{{ item.content.slice(0, 280) }}…</p>
            <details><summary>查看完整资料</summary><p class="passage">{{ item.content }}</p></details>
          </template>
        </article>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import axios from 'axios'
import { useAuthStore } from '../../stores/auth'
import { useTeacherStore } from '../../stores/teacher'
import type { SubjectAgentCode, SubjectKnowledgeItem, SubjectKnowledgeSearchResult } from '../../api/types'

const auth = useAuthStore()
const teacher = useTeacherStore()
const labels: Record<string, string> = {
  chinese: '语文', math: '数学', english: '英语', politics: '道法', history: '历史',
  physics: '物理', chemistry: '化学', geography: '地理', biology: '生物'
}
const subject = computed<SubjectAgentCode | ''>(() => Object.prototype.hasOwnProperty.call(labels, auth.activeSubject) ? auth.activeSubject as SubjectAgentCode : '')
const subjectLabel = computed(() => labels[subject.value] ?? '学科')
const entryMode = ref<'text' | 'pdf'>('text')
const title = ref('')
const sourceName = ref('')
const content = ref('')
const pdfFile = ref<File | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const items = ref<SubjectKnowledgeItem[]>([])
const vectorEnabled = ref(false)
const loading = ref(false)
const saving = ref(false)
const importing = ref(false)
const reindexing = ref(false)
const deletingId = ref<number | null>(null)
const searching = ref(false)
const mutating = computed(() => saving.value || importing.value || reindexing.value || deletingId.value !== null || searching.value)
const error = ref('')
const notice = ref('')
const warnings = ref<string[]>([])
const query = ref('')
const searchResult = ref<SubjectKnowledgeSearchResult | null>(null)
let generation = 0
let loadSequence = 0

function errorMessage(cause: unknown, fallback: string): string {
  if (axios.isAxiosError(cause)) {
    const detail = cause.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (cause.code === 'ECONNABORTED') return '处理时间较长，请刷新资料列表确认结果后再操作。'
  }
  return fallback
}

function clearFeedback() {
  error.value = ''; notice.value = ''; warnings.value = []
}

function clearForm() {
  title.value = ''; sourceName.value = ''; content.value = ''; pdfFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

async function load(expectedGeneration = generation) {
  const target = subject.value
  if (!target || expectedGeneration !== generation) return
  const sequence = ++loadSequence
  loading.value = true
  try {
    const result = await teacher.fetchSubjectKnowledge(target)
    if (expectedGeneration !== generation || sequence !== loadSequence) return
    items.value = result.items
    vectorEnabled.value = result.vector_enabled
  } catch (cause) {
    if (expectedGeneration === generation && sequence === loadSequence) error.value = errorMessage(cause, '知识库读取失败，请稍后刷新。')
  } finally {
    if (expectedGeneration === generation && sequence === loadSequence) loading.value = false
  }
}

async function save() {
  const target = subject.value
  if (!target || mutating.value || !title.value.trim() || !content.value.trim()) return
  const current = generation
  saving.value = true
  clearFeedback()
  try {
    const result = await teacher.addSubjectKnowledge(target, {
      title: title.value.trim(), content: content.value.trim(), source_name: sourceName.value.trim() || undefined
    })
    if (current !== generation) return
    clearForm()
    notice.value = `资料已保存，可检索 ${result.passage_count} 个片段。`
    warnings.value = result.warnings ?? []
    searchResult.value = null
    await load(current)
  } catch (cause) {
    if (current === generation) error.value = errorMessage(cause, '资料添加失败，请稍后重试。')
  } finally {
    if (current === generation) saving.value = false
  }
}

function selectPdf(event: Event) {
  clearFeedback()
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  pdfFile.value = null
  if (!file) return
  if (!/\.pdf$/i.test(file.name)) {
    error.value = '请选择 PDF 文件。'
    input.value = ''
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    error.value = 'PDF 不能超过 10 MB，请拆分后导入。'
    input.value = ''
    return
  }
  pdfFile.value = file
}

async function importPdf() {
  const target = subject.value
  const file = pdfFile.value
  if (!target || !file || mutating.value) return
  const current = generation
  importing.value = true
  clearFeedback()
  try {
    const result = await teacher.importSubjectKnowledgePdf(target, file, {
      title: title.value.trim() || undefined, source_name: sourceName.value.trim() || undefined
    })
    if (current !== generation) return
    clearForm()
    notice.value = `PDF 已导入${result.indexed_pages == null ? '' : `，读取 ${result.indexed_pages} 页`}，可检索 ${result.passage_count} 个片段。`
    warnings.value = result.warnings ?? []
    searchResult.value = null
    await load(current)
  } catch (cause) {
    if (current === generation) error.value = errorMessage(cause, 'PDF 导入失败，请检查文件后重试。')
  } finally {
    if (current === generation) importing.value = false
  }
}

async function search() {
  const target = subject.value
  if (!target || !query.value.trim() || searching.value || mutating.value) return
  const current = generation
  searching.value = true
  error.value = ''
  searchResult.value = null
  try {
    const result = await teacher.searchSubjectKnowledge(target, query.value.trim())
    if (current === generation) searchResult.value = result
  } catch (cause) {
    if (current === generation) error.value = errorMessage(cause, '资料检索失败，请稍后重试。')
  } finally {
    if (current === generation) searching.value = false
  }
}

async function reindex() {
  const target = subject.value
  if (!target || mutating.value || !vectorEnabled.value) return
  const current = generation
  reindexing.value = true
  clearFeedback()
  try {
    const result = await teacher.reindexSubjectKnowledge(target)
    if (current !== generation) return
    notice.value = result.vector_status === 'ready'
      ? `索引已更新，共 ${result.documents} 份资料、${result.passage_count} 个片段。`
      : '资料已保留，向量索引尚未完成；当前仍可使用关键词检索。'
    warnings.value = result.warnings ?? []
    searchResult.value = null
    await load(current)
  } catch (cause) {
    if (current === generation) {
      error.value = axios.isAxiosError(cause) && cause.code === 'ECONNABORTED'
        ? '索引重建仍可能在处理中，请稍后用“试查资料”确认检索结果。'
        : errorMessage(cause, '索引更新失败，请稍后重试。')
    }
  } finally {
    if (current === generation) reindexing.value = false
  }
}

async function remove(item: SubjectKnowledgeItem) {
  const target = subject.value
  if (!target || mutating.value || !window.confirm(`删除「${item.title}」？`)) return
  const current = generation
  deletingId.value = item.id
  clearFeedback()
  try {
    const result = await teacher.deleteSubjectKnowledge(target, item.id)
    if (current !== generation) return
    notice.value = '资料已删除。'
    warnings.value = result.warnings ?? []
    searchResult.value = null
    await load(current)
  } catch (cause) {
    if (current === generation) error.value = errorMessage(cause, '删除失败，请稍后重试。')
  } finally {
    if (current === generation) deletingId.value = null
  }
}

watch(subject, () => {
  generation += 1
  items.value = []; vectorEnabled.value = false
  loading.value = false; saving.value = false; importing.value = false; reindexing.value = false; deletingId.value = null
  searching.value = false; searchResult.value = null; query.value = ''
  clearFeedback(); clearForm()
  void load()
}, { immediate: true })
</script>

<style scoped>
.feedback:empty { display: none; }
.feedback p { margin: 0 0 12px; }
.notice, .warning { padding: 11px 14px; border-radius: 8px; font-size: 13px; line-height: 1.6; }
.notice { color: #166534; background: #f0fdf4; }
.warning { color: #92400e; background: #fffbeb; }
.entry-modes { display: flex; gap: 6px; margin-bottom: 20px; }
.entry-modes button { padding: 8px 14px; border: 1px solid var(--border); background: var(--bg); color: var(--text-2); border-radius: 8px; cursor: pointer; font: inherit; font-size: 13px; }
.entry-modes button.selected { background: var(--primary); border-color: var(--primary); color: #fff; }
.entry-modes button:disabled { opacity: .6; cursor: default; }
.form-row textarea { width: 100%; resize: vertical; line-height: 1.65; }
.form-row input[type='file'] { max-width: 100%; font-size: 13px; }
.file-name { font-size: 13px; color: var(--text-2); overflow-wrap: anywhere; }
.section-hint, .result-summary, .source { color: var(--text-3); font-size: 13px; line-height: 1.6; }
.section-hint { margin: 8px 0 16px; }
.search-form { display: flex; gap: 10px; }
.search-form input { min-width: 0; flex: 1; }
.knowledge-head, .knowledge-item header, .result-head { display: flex; justify-content: space-between; align-items: center; gap: 14px; }
.knowledge-head { flex-wrap: wrap; }
.knowledge-head h3 { margin: 0; }
.head-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.count { color: var(--text-3); font-size: 13px; font-weight: 500; }
.knowledge-item, .search-result { padding: 16px 0; border-top: 1px solid var(--border); }
.knowledge-item header > div { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.knowledge-item b, .result-head b { overflow-wrap: anywhere; }
.knowledge-item small { color: var(--text-3); }
.passage { margin: 10px 0 0; color: var(--text-2); font-size: 13.5px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.knowledge-item details { margin-top: 10px; }
.knowledge-item summary { color: var(--text-3); font-size: 13px; cursor: pointer; }
.result-head { flex-wrap: wrap; align-items: baseline; }
.citation { color: var(--text-3); font-size: 12px; }
.source { margin: 5px 0 0; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (max-width: 600px) {
  .search-form { flex-direction: column; }
  .search-form .btn { align-self: flex-start; }
  .knowledge-head { align-items: flex-start; }
}
</style>
