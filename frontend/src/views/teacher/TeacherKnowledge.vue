<template>
  <div class="page materials-page">
    <header class="materials-heading">
      <div>
        <div class="agent-badge"><span class="agent-pulse"></span>{{ subjectLabel }} Agent <span class="badge-divider">·</span> 专属知识库</div>
        <h2>我的资料</h2>
      </div>
      <button class="reindex-button" :disabled="loading || mutating || !vectorEnabled || !items.length" @click="reindex">
        <span class="refresh-symbol">↻</span>{{ reindexing ? '正在更新索引…' : '重建检索索引' }}
      </button>
    </header>

    <div v-if="!subject" class="empty-state">教师登录时需要先选择任教学科。</div>
    <template v-else>
      <div class="feedback" aria-live="polite">
        <p v-if="error" class="error-msg" role="alert">{{ error }}</p>
        <p v-if="notice" class="notice">{{ notice }}</p>
        <p v-for="warning in warnings" :key="warning" class="warning">{{ warning }}</p>
      </div>

      <section class="bookshelf-panel">
        <div class="shelf-heading">
          <div>
            <div class="shelf-title-line"><h3>知识库书架</h3><span class="document-count">{{ items.length }} 份资料</span></div>
          </div>
          <span :class="['index-status', vectorEnabled ? 'ready' : 'keyword']"><i></i>{{ vectorEnabled ? '语义 + 关键词检索' : '关键词检索' }}</span>
        </div>

        <div v-if="loading" class="shelf-loading">正在整理资料书架…</div>
        <div v-else class="shelf-scene">
          <div class="books-row">
            <article v-for="item in items" :key="item.id" class="document-slot">
              <button class="document-cover" :style="bookStyle(item)" :aria-label="`打开资料：${item.title}`" @click="activeDocument = item">
                <span class="cover-top"><span class="cover-monogram">{{ subjectLabel.slice(0, 1) }}</span><span class="cover-kind">{{ documentFormat(item) }}</span></span>
                <span class="cover-title">{{ item.title }}</span>
                <span class="cover-rule"></span>
                <span class="cover-source">{{ item.source_name || '教师整理' }}</span>
                <span class="cover-footer">{{ item.passage_count }} 个检索片段</span>
              </button>
              <div class="document-caption">
                <b :title="item.title">{{ item.title }}</b>
                <small>{{ item.source_name || '教师整理' }}</small>
              </div>
            </article>

            <button class="add-document-slot" :disabled="mutating" @click="openUpload('file')">
              <span class="add-document-card"><span class="add-plus">+</span><b>添加资料</b></span>
            </button>
          </div>
          <div class="shelf-board"></div>
          <p v-if="!items.length" class="shelf-empty">暂无资料</p>
        </div>
      </section>

      <section class="search-panel">
        <div class="search-heading">
          <span class="search-mark">⌕</span>
          <div><h3>试查 Agent 检索</h3></div>
        </div>
        <form class="search-form" @submit.prevent="search">
          <label class="sr-only" for="knowledge-query">试查问题</label>
          <input id="knowledge-query" v-model="query" maxlength="1000" placeholder="例如：一次函数的图像如何判断增减性？" :disabled="searching" />
          <button class="search-button" type="submit" :disabled="searching || mutating || !query.trim()">{{ searching ? '检索中…' : '检索资料' }}</button>
        </form>
        <template v-if="searchResult">
          <div class="result-summary">{{ searchResult.retrieval_mode === 'hybrid' ? '混合检索' : '关键词检索' }} · 找到 {{ searchResult.items.length }} 条相关内容</div>
          <p v-for="warning in searchResult.warnings" :key="warning" class="warning">{{ warning }}</p>
          <div v-if="!searchResult.items.length" class="search-empty">暂时没有找到相关资料，可以换个问法或补充文档。</div>
          <article v-for="result in searchResult.items" :key="`${result.document_id}-${result.passage_id}`" class="search-result">
            <div class="result-head"><b>{{ result.title }}</b><span class="citation">{{ result.citation }}</span></div>
            <p class="source">来源：{{ result.source_name || '教师整理' }}<span v-if="result.page_number"> · 第 {{ result.page_number }} 页</span></p>
            <p class="passage">{{ result.content }}</p>
          </article>
        </template>
      </section>
    </template>

    <div v-if="uploadOpen" class="modal-mask" tabindex="-1" @keydown.esc="closeUpload" @click.self="closeUpload">
      <section class="upload-dialog" role="dialog" aria-modal="true" aria-labelledby="upload-title">
        <header class="dialog-heading">
          <div><span class="dialog-eyebrow">{{ subjectLabel }} Agent 知识库</span><h3 id="upload-title">添加资料</h3></div>
          <button class="close-dialog" type="button" aria-label="关闭" :disabled="mutating && !importing" @click="closeUpload">×</button>
        </header>
        <div class="entry-modes" role="tablist" aria-label="资料添加方式">
          <button type="button" role="tab" :aria-selected="entryMode === 'text'" :class="{ selected: entryMode === 'text' }" :disabled="mutating" @click="entryMode = 'text'">粘贴文字</button>
          <button type="button" role="tab" :aria-selected="entryMode === 'file'" :class="{ selected: entryMode === 'file' }" :disabled="mutating" @click="entryMode = 'file'">导入文档</button>
        </div>
        <div v-if="entryMode === 'file'" class="upload-dropzone">
          <span class="file-icon">{{ documentFile ? documentFile.name.split('.').pop()?.toUpperCase() : 'FILE' }}</span>
          <div><b>{{ documentFile ? documentFile.name : '选择一份资料文档' }}</b></div>
          <label class="choose-file" for="knowledge-document">{{ documentFile ? '重新选择' : '选择文件' }}</label>
          <input id="knowledge-document" ref="fileInput" class="sr-only" type="file" :accept="documentAccept" :disabled="mutating" @change="selectDocument" />
        </div>
        <p v-if="entryMode === 'file'" class="scan-note">支持 PDF、图片、Office 文档和常见文本格式</p>
        <div v-if="entryMode === 'text'" class="dialog-form-row">
          <label for="knowledge-title">资料标题</label>
          <input id="knowledge-title" v-model="title" class="dialog-input" maxlength="160" :disabled="mutating" placeholder="例如：一次函数图像与性质" />
        </div>
        <div v-if="entryMode === 'text'" class="dialog-form-row">
          <label for="knowledge-source">资料来源 <span>（选填）</span></label>
          <input id="knowledge-source" v-model="sourceName" class="dialog-input" maxlength="200" :disabled="mutating" placeholder="例如：七年级下册教材 / 第三章讲义" />
        </div>
        <div v-if="entryMode === 'text'" class="dialog-form-row">
          <label for="knowledge-content">资料内容</label>
          <textarea id="knowledge-content" v-model="content" class="dialog-textarea" rows="7" maxlength="20000" :disabled="mutating" placeholder="粘贴教材内容、讲义、解题方法或评分标准。文档只供当前学科 Agent 检索。" />
          <small class="character-count">{{ content.length }} / 20000 字</small>
        </div>
        <p v-if="error" class="dialog-error" role="alert">{{ error }}</p>
        <footer class="dialog-actions">
          <button class="cancel-button" type="button" :disabled="mutating && !importing" @click="closeUpload">{{ importing ? '收起窗口' : '取消' }}</button>
          <button v-if="entryMode === 'text'" class="save-button" type="button" :disabled="mutating || !title.trim() || !content.trim()" @click="save">{{ saving ? '正在保存…' : '保存到知识库' }}</button>
          <button v-else class="save-button" type="button" :disabled="mutating || !documentFile" @click="importDocument">{{ importing ? '正在导入…' : '导入到知识库' }}</button>
        </footer>
      </section>
    </div>

    <div v-if="activeDocument" class="modal-mask" tabindex="-1" @keydown.esc="activeDocument = null" @click.self="activeDocument = null">
      <section class="document-dialog" role="dialog" aria-modal="true" :aria-label="activeDocument.title">
        <header class="document-dialog-head">
          <span class="preview-cover" :style="bookStyle(activeDocument)">{{ subjectLabel.slice(0, 1) }}</span>
          <div class="preview-title"><span class="dialog-eyebrow">{{ importedDocumentLabel(activeDocument) }}</span><h3>{{ activeDocument.title }}</h3><small>{{ activeDocument.source_name || '教师整理' }} · {{ activeDocument.passage_count }} 个检索片段</small></div>
          <button class="close-dialog" type="button" aria-label="关闭" @click="activeDocument = null">×</button>
        </header>
        <div class="document-content">{{ activeDocument.content }}</div>
        <footer class="dialog-actions">
          <button class="delete-button" type="button" :disabled="mutating" @click="askToRemove(activeDocument)">{{ deletingId === activeDocument.id ? '正在删除…' : '删除资料' }}</button>
          <button class="save-button" type="button" @click="activeDocument = null">完成</button>
        </footer>
      </section>
    </div>

    <div
      v-if="deleteConfirmDocument"
      class="modal-mask delete-confirm-mask"
      tabindex="-1"
      @keydown.esc="deleteConfirmDocument = null"
      @click.self="deleteConfirmDocument = null"
    >
      <section
        class="delete-confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="delete-confirm-title"
        aria-describedby="delete-confirm-description"
      >
        <span class="delete-confirm-icon" aria-hidden="true">!</span>
        <h3 id="delete-confirm-title">删除这份资料？</h3>
        <p id="delete-confirm-description">确定删除「{{ deleteConfirmDocument.title }}」？删除后无法恢复。</p>
        <footer class="delete-confirm-actions">
          <button ref="deleteConfirmCancelButton" class="cancel-button" type="button" @click="deleteConfirmDocument = null">取消</button>
          <button class="confirm-delete-button" type="button" @click="confirmRemove">删除资料</button>
        </footer>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
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
const entryMode = ref<'text' | 'file'>('text')
const uploadOpen = ref(false)
const activeDocument = ref<SubjectKnowledgeItem | null>(null)
const deleteConfirmDocument = ref<SubjectKnowledgeItem | null>(null)
const deleteConfirmCancelButton = ref<HTMLButtonElement | null>(null)
const title = ref('')
const sourceName = ref('')
const content = ref('')
const documentFile = ref<File | null>(null)
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

const BOOK_COLORS = ['#2556C9', '#087A73', '#B76C27', '#9E4765', '#6552A2', '#3C718B']
const supportedDocumentFormats = new Set([
  'pdf', 'docx', 'pptx', 'xlsx', 'xlsm', 'txt', 'md', 'csv', 'tsv', 'html', 'htm', 'json', 'xml', 'yaml', 'yml',
  'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff'
])
const documentAccept = [...supportedDocumentFormats].map(format => `.${format}`).join(',')

function bookStyle(item: SubjectKnowledgeItem): Record<string, string> {
  const color = BOOK_COLORS[(item.id - 1) % BOOK_COLORS.length]
  return { background: `linear-gradient(148deg, ${color} 0%, ${color} 54%, #17233E 100%)` }
}

function documentFormat(item: SubjectKnowledgeItem): string {
  const filename = item.source_name || item.title
  const extension = filename.match(/\.([a-z0-9]+)$/i)?.[1]?.toUpperCase()
  return extension && supportedDocumentFormats.has(extension.toLowerCase())
    ? extension
    : 'TEXT'
}

function importedDocumentLabel(item: SubjectKnowledgeItem): string {
  const format = documentFormat(item)
  return format === 'TEXT' ? '文字资料' : `${format} 资料`
}

function openUpload(mode: 'text' | 'file' = 'text') {
  if (mutating.value) return
  clearFeedback()
  clearForm()
  entryMode.value = mode
  uploadOpen.value = true
}

function closeUpload() {
  if (mutating.value && !importing.value) return
  uploadOpen.value = false
  error.value = ''
  if (!importing.value) clearForm()
}

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
  title.value = ''; sourceName.value = ''; content.value = ''; documentFile.value = null
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
    uploadOpen.value = false
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

function selectDocument(event: Event) {
  clearFeedback()
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  documentFile.value = null
  if (!file) return
  const extension = file.name.match(/\.([^.]+)$/)?.[1]?.toLowerCase()
  if (!extension || !supportedDocumentFormats.has(extension)) {
    error.value = '暂不支持此格式，请选择 PDF、图片、Office 文档或文本文件。'
    input.value = ''
    return
  }
  documentFile.value = file
  input.value = ''
}

async function importDocument() {
  const target = subject.value
  const file = documentFile.value
  if (!target || !file || mutating.value) return
  const current = generation
  importing.value = true
  clearFeedback()
  try {
    await teacher.importSubjectKnowledgeDocument(target, file)
    if (current !== generation) return
    clearForm()
    uploadOpen.value = false
    notice.value = ''
    warnings.value = []
    searchResult.value = null
  } catch {
    // 上传结果由应用外壳中的全局提示卡展示，避免在资料页重复报错。
  } finally {
    importing.value = false
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

function askToRemove(item: SubjectKnowledgeItem) {
  if (!mutating.value) deleteConfirmDocument.value = item
}

function confirmRemove() {
  const item = deleteConfirmDocument.value
  if (item) void remove(item)
}

watch(deleteConfirmDocument, async item => {
  if (!item) return
  await nextTick()
  deleteConfirmCancelButton.value?.focus()
})

async function remove(item: SubjectKnowledgeItem) {
  const target = subject.value
  if (!target || mutating.value) return
  deleteConfirmDocument.value = null
  const current = generation
  deletingId.value = item.id
  clearFeedback()
  try {
    const result = await teacher.deleteSubjectKnowledge(target, item.id)
    if (current !== generation) return
    activeDocument.value = null
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
  uploadOpen.value = false; activeDocument.value = null; deleteConfirmDocument.value = null
  clearFeedback(); clearForm()
  void load()
}, { immediate: true })

watch(() => subject.value ? teacher.knowledgeImportVersions[subject.value] ?? 0 : 0, () => {
  void load()
})
</script>

<style scoped>
.materials-page { max-width: 1320px; margin: 0 auto; }
.materials-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin: 2px 0 24px; }
.materials-heading h2 { margin: 7px 0 5px; font-size: 30px; letter-spacing: -.5px; }
.page-sub { max-width: 680px; color: var(--text-3); font-size: 14px; line-height: 1.65; }
.agent-badge { display: inline-flex; align-items: center; gap: 8px; color: #3157A5; font-size: 12px; font-weight: 700; letter-spacing: .02em; }
.agent-pulse { width: 8px; height: 8px; border-radius: 50%; background: #28A879; box-shadow: 0 0 0 4px #E7F7F0; }
.badge-divider { color: #9AA7BC; }
.reindex-button, .search-button, .save-button { border: 0; border-radius: 10px; background: var(--primary); color: #fff; font: inherit; font-weight: 700; cursor: pointer; transition: transform .18s ease, box-shadow .18s ease, opacity .18s ease; }
.reindex-button { display: inline-flex; align-items: center; gap: 7px; padding: 10px 14px; white-space: nowrap; box-shadow: 0 5px 14px rgba(37, 86, 201, .16); }
.reindex-button:hover:not(:disabled), .search-button:hover:not(:disabled), .save-button:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 7px 18px rgba(37, 86, 201, .2); }
.reindex-button:disabled, .search-button:disabled, .save-button:disabled { opacity: .48; cursor: default; }
.refresh-symbol { font-size: 18px; line-height: 1; }
.feedback:empty { display: none; }
.feedback p { margin: 0 0 12px; }
.notice, .warning { padding: 11px 14px; border-radius: 10px; font-size: 13px; line-height: 1.6; }
.notice { color: #166534; background: #f0fdf4; }
.warning { color: #92400e; background: #fffbeb; }
.bookshelf-panel { overflow: hidden; border: 1px solid #E5EAF1; border-radius: 18px; background: linear-gradient(180deg, #fff 0%, #FAFBFE 100%); box-shadow: 0 10px 30px rgba(28, 44, 75, .055); }
.shelf-heading { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 22px 26px 18px; border-bottom: 1px solid rgba(223, 229, 239, .82); }
.shelf-title-line { display: flex; align-items: center; gap: 12px; }
.shelf-title-line h3, .search-heading h3 { margin: 0; color: var(--text); font-size: 17px; }
.document-count { padding: 4px 9px; border-radius: 999px; background: #EFF4FF; color: #3157A5; font-size: 12px; font-weight: 700; }
.shelf-heading p, .search-heading p { margin: 6px 0 0; color: var(--text-3); font-size: 13px; }
.index-status { display: inline-flex; align-items: center; gap: 7px; padding: 7px 10px; border: 1px solid #E7EBF1; border-radius: 999px; background: #fff; color: var(--text-2); font-size: 12px; white-space: nowrap; }
.index-status i { width: 7px; height: 7px; border-radius: 50%; background: #D39A37; }
.index-status.ready i { background: #20A574; box-shadow: 0 0 0 3px #E4F6EE; }
.shelf-scene { padding: 24px 28px 18px; background: radial-gradient(ellipse at 50% 0%, rgba(245, 238, 220, .52), transparent 68%); }
.shelf-loading { display: grid; min-height: 230px; place-items: center; color: var(--text-3); font-size: 14px; }
.books-row { display: grid; grid-template-columns: repeat(auto-fill, minmax(132px, 148px)); align-items: end; justify-content: start; gap: 26px 24px; min-height: 226px; padding: 8px 6px 0; }
.document-slot { min-width: 0; text-align: center; }
.document-cover { position: relative; display: flex; width: 126px; height: 172px; flex-direction: column; align-items: stretch; margin: 0 auto; padding: 13px 12px 11px 16px; overflow: hidden; border: 0; border-radius: 3px 8px 8px 3px; color: #fff; text-align: left; cursor: pointer; box-shadow: inset 5px 0 10px rgba(0, 0, 0, .22), inset -2px 0 4px rgba(255, 255, 255, .18), 0 8px 18px rgba(19, 38, 72, .24); transition: transform .22s ease, box-shadow .22s ease; }
.document-cover::before { position: absolute; inset: 0 auto 0 8px; width: 1px; background: rgba(255,255,255,.22); content: ''; }
.document-cover::after { position: absolute; inset: 0; background: linear-gradient(108deg, rgba(255,255,255,.13), transparent 35%, transparent 76%, rgba(0,0,0,.12)); content: ''; pointer-events: none; }
.document-cover:hover { transform: translateY(-7px) rotate(-1deg); box-shadow: inset 5px 0 10px rgba(0, 0, 0, .22), 0 14px 22px rgba(19, 38, 72, .27); }
.cover-top, .cover-title, .cover-rule, .cover-source, .cover-footer { position: relative; z-index: 1; }
.cover-top { display: flex; align-items: center; justify-content: space-between; }
.cover-monogram { display: grid; width: 28px; height: 28px; place-items: center; border: 1px solid rgba(255,255,255,.38); border-radius: 8px; background: rgba(255,255,255,.16); font-size: 15px; font-weight: 800; }
.cover-kind { color: rgba(255,255,255,.72); font-size: 9px; font-weight: 700; letter-spacing: .1em; }
.cover-title { display: -webkit-box; min-height: 48px; margin-top: 22px; overflow: hidden; font-size: 14px; font-weight: 750; line-height: 1.55; text-align: center; text-overflow: ellipsis; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow-wrap: anywhere; }
.cover-rule { width: 48px; height: 1px; margin: 10px auto 8px; background: rgba(255,255,255,.46); }
.cover-source { display: -webkit-box; overflow: hidden; color: rgba(255,255,255,.76); font-size: 10px; line-height: 1.4; text-align: center; text-overflow: ellipsis; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow-wrap: anywhere; }
.cover-footer { margin-top: auto; color: rgba(255,255,255,.72); font-size: 9px; text-align: center; }
.document-caption { display: flex; flex-direction: column; gap: 4px; width: 140px; margin: 10px auto 0; text-align: left; }
.document-caption b { overflow: hidden; color: var(--text); font-size: 12px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }
.document-caption small { overflow: hidden; color: var(--text-3); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.add-document-slot { display: flex; width: 148px; flex-direction: column; justify-content: flex-end; padding: 0; border: 0; background: transparent; color: var(--text-2); font: inherit; cursor: pointer; }
.add-document-slot:disabled { opacity: .55; cursor: default; }
.add-document-card { display: flex; width: 126px; height: 172px; flex-direction: column; align-items: center; justify-content: center; gap: 7px; margin: 0 auto; padding: 12px; border: 2px dashed #B9CAF3; border-radius: 9px; background: rgba(255,255,255,.72); color: var(--primary); transition: background .2s ease, border-color .2s ease, transform .2s ease; }
.add-document-slot:hover:not(:disabled) .add-document-card { transform: translateY(-5px); border-color: var(--primary); background: #F3F6FF; }
.add-plus { font-size: 34px; font-weight: 300; line-height: 1; }
.add-document-card b { font-size: 13px; }
.add-document-card small { color: var(--text-3); font-size: 10px; line-height: 1.4; }
.shelf-board { height: 13px; margin-top: 3px; border-radius: 3px; background: linear-gradient(180deg, #C99D70 0%, #A97A4D 55%, #87582F 100%); box-shadow: 0 10px 15px rgba(90, 58, 25, .2), inset 0 1px 0 rgba(255,255,255,.48); }
.shelf-empty { margin: 22px 4px 2px; color: var(--text-3); font-size: 13px; }
.search-panel { margin-top: 20px; padding: 20px 24px; border: 1px solid #E5EAF1; border-radius: 16px; background: #fff; box-shadow: 0 7px 22px rgba(28, 44, 75, .045); }
.search-heading { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.search-mark { display: grid; width: 38px; height: 38px; flex: 0 0 auto; place-items: center; border-radius: 12px; background: #EFF4FF; color: var(--primary); font-size: 27px; line-height: 1; }
.search-form { display: flex; gap: 10px; }
.search-form input, .dialog-input, .dialog-textarea { width: 100%; min-width: 0; border: 1px solid #DDE3ED; border-radius: 10px; background: #FBFCFE; color: var(--text); font: inherit; outline: none; transition: border-color .15s ease, box-shadow .15s ease, background .15s ease; }
.search-form input { flex: 1; height: 48px; padding: 0 14px; }
.search-form input:focus, .dialog-input:focus, .dialog-textarea:focus { border-color: #7A9CF5; background: #fff; box-shadow: 0 0 0 3px rgba(37, 86, 201, .11); }
.search-button { min-width: 112px; padding: 0 18px; }
.search-button:disabled { opacity: .5; cursor: default; }
.result-summary { margin: 16px 0 4px; color: var(--text-3); font-size: 12px; }
.search-empty { padding: 18px; border-radius: 10px; background: #F7F9FC; color: var(--text-3); font-size: 13px; text-align: center; }
.search-result { padding: 15px 0; border-top: 1px solid #EDF0F5; }
.result-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px 14px; }
.result-head b { color: var(--text); font-size: 14px; overflow-wrap: anywhere; }
.citation { padding: 4px 8px; border-radius: 999px; background: #F0F4FB; color: #52647F; font-size: 11px; }
.source { margin: 6px 0 0; color: var(--text-3); font-size: 12px; }
.passage { margin: 9px 0 0; color: var(--text-2); font-size: 13px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.modal-mask { position: fixed; inset: 0; z-index: 300; display: flex; align-items: center; justify-content: center; padding: 22px; background: rgba(15, 23, 42, .46); backdrop-filter: blur(4px); }
.delete-confirm-mask { z-index: 320; }
.upload-dialog, .document-dialog { width: min(590px, 100%); max-height: min(88dvh, 820px); overflow: auto; border: 1px solid rgba(255,255,255,.7); border-radius: 18px; background: #fff; box-shadow: 0 28px 80px rgba(16, 31, 58, .28); animation: dialog-in .18s ease both; }
.upload-dialog { padding: 23px; }
.dialog-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.dialog-heading h3, .preview-title h3 { margin: 3px 0 0; color: var(--text); font-size: 21px; }
.dialog-eyebrow { color: #5271B4; font-size: 11px; font-weight: 750; letter-spacing: .04em; }
.close-dialog { display: grid; width: 34px; height: 34px; flex: 0 0 auto; place-items: center; border: 1px solid #E8ECF2; border-radius: 10px; background: #F8FAFD; color: #64748B; font-size: 23px; line-height: 1; cursor: pointer; }
.close-dialog:hover { background: #EEF2F8; color: var(--text); }
.entry-modes { display: inline-flex; gap: 4px; margin-bottom: 18px; padding: 4px; border-radius: 11px; background: #F1F4F8; }
.entry-modes button { padding: 8px 14px; border: 0; border-radius: 8px; background: transparent; color: var(--text-2); font: inherit; font-size: 13px; cursor: pointer; }
.entry-modes button.selected { background: #fff; color: var(--primary); box-shadow: 0 2px 7px rgba(23, 37, 62, .1); font-weight: 700; }
.entry-modes button:disabled { opacity: .55; cursor: default; }
.upload-dropzone { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; padding: 14px; border: 1px dashed #B9CAF3; border-radius: 12px; background: #F7F9FF; }
.file-icon { display: grid; width: 48px; min-height: 46px; flex: 0 0 auto; place-items: center; padding: 0 5px; border-radius: 9px; background: #E7EDFF; color: var(--primary); font-size: 10px; font-weight: 800; overflow-wrap: anywhere; text-align: center; }
.upload-dropzone > div { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 4px; }
.upload-dropzone b { overflow: hidden; color: var(--text); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.upload-dropzone small, .scan-note { color: var(--text-3); font-size: 11px; }
.choose-file { padding: 8px 11px; border: 1px solid #D9E2F5; border-radius: 8px; background: #fff; color: var(--primary); font-size: 12px; font-weight: 700; white-space: nowrap; cursor: pointer; }
.scan-note { margin: 0 0 12px; }
.dialog-form-row { margin-top: 14px; }
.dialog-form-row label { display: block; margin-bottom: 7px; color: var(--text-2); font-size: 12px; font-weight: 700; }
.dialog-form-row label span { color: var(--text-3); font-weight: 400; }
.dialog-input { height: 43px; padding: 0 12px; font-size: 13px; }
.dialog-textarea { min-height: 150px; padding: 11px 12px; resize: vertical; font-size: 13px; line-height: 1.65; }
.character-count { display: block; margin-top: 5px; color: var(--text-3); font-size: 11px; text-align: right; }
.dialog-error { margin: 12px 0 0; color: #B42318; font-size: 12px; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 9px; margin-top: 20px; padding-top: 16px; border-top: 1px solid #EDF0F5; }
.cancel-button, .delete-button { padding: 9px 14px; border: 1px solid #DDE3ED; border-radius: 9px; background: #fff; color: var(--text-2); font: inherit; font-size: 13px; font-weight: 650; cursor: pointer; }
.cancel-button:hover { background: #F7F9FC; }
.save-button { min-height: 40px; padding: 9px 16px; font-size: 13px; }
.delete-button { margin-right: auto; border-color: #F4D1CF; color: #B42318; }
.delete-button:hover { background: #FFF6F5; }
.delete-confirm-dialog { width: min(420px, 100%); padding: 25px; border: 1px solid rgba(255,255,255,.7); border-radius: 16px; background: #fff; box-shadow: 0 28px 80px rgba(16, 31, 58, .3); animation: dialog-in .18s ease both; }
.delete-confirm-icon { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 50%; background: #FFF0EF; color: #B42318; font-size: 22px; font-weight: 800; }
.delete-confirm-dialog h3 { margin: 16px 0 7px; color: var(--text); font-size: 18px; }
.delete-confirm-dialog p { margin: 0; color: var(--text-2); font-size: 13px; line-height: 1.65; overflow-wrap: anywhere; }
.delete-confirm-actions { display: flex; justify-content: flex-end; gap: 9px; margin-top: 22px; }
.confirm-delete-button { padding: 9px 14px; border: 1px solid #B42318; border-radius: 9px; background: #B42318; color: #fff; font: inherit; font-size: 13px; font-weight: 650; cursor: pointer; }
.confirm-delete-button:hover { border-color: #912018; background: #912018; }
.document-dialog { padding: 22px; }
.document-dialog-head { display: flex; align-items: center; gap: 14px; }
.preview-cover { display: grid; width: 54px; height: 70px; flex: 0 0 auto; place-items: center; border-radius: 3px 6px 6px 3px; color: #fff; font-size: 23px; font-weight: 800; box-shadow: inset 4px 0 8px rgba(0,0,0,.2), 0 5px 12px rgba(15,23,42,.2); }
.preview-title { min-width: 0; flex: 1; }
.preview-title h3 { overflow-wrap: anywhere; font-size: 18px; }
.preview-title small { display: block; margin-top: 5px; color: var(--text-3); font-size: 11px; }
.document-content { max-height: 55vh; margin-top: 19px; padding: 16px; overflow: auto; border: 1px solid #EDF0F5; border-radius: 11px; background: #FBFCFE; color: var(--text-2); font-size: 13px; line-height: 1.75; white-space: pre-wrap; overflow-wrap: anywhere; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@keyframes dialog-in { from { opacity: 0; transform: translateY(8px) scale(.99); } to { opacity: 1; transform: translateY(0) scale(1); } }
@media (max-width: 720px) {
  .materials-heading { align-items: flex-start; flex-direction: column; gap: 14px; }
  .materials-heading h2 { font-size: 25px; }
  .reindex-button { align-self: flex-start; }
  .shelf-heading { align-items: flex-start; flex-direction: column; padding: 18px 18px 15px; }
  .shelf-scene { padding: 18px 16px 14px; }
  .books-row { grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 22px 8px; }
  .document-cover, .add-document-card { width: 112px; height: 156px; }
  .document-caption { width: 122px; }
  .add-document-slot { width: 122px; }
  .search-panel { padding: 18px 16px; }
}
@media (max-width: 480px) {
  .books-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .search-form { flex-direction: column; }
  .search-button { min-height: 44px; }
  .upload-dialog, .document-dialog { padding: 17px; }
  .upload-dropzone { flex-wrap: wrap; }
  .choose-file { margin-left: 54px; }
}
@media (prefers-reduced-motion: reduce) {
  .document-cover, .add-document-card, .reindex-button, .search-button, .save-button { transition: none; }
  .document-cover:hover, .add-document-slot:hover .add-document-card { transform: none; }
  .upload-dialog, .document-dialog { animation: none; }
}
</style>
