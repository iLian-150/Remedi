<template>
  <div class="page">
    <div class="page-head">
      <h2>{{ subjectLabel }} Agent 知识库</h2>
      <p class="page-sub">资料只进入当前学科 Agent 的检索库；学生提问时按学科检索相关片段，再结合本人错题与学习记忆回答。</p>
    </div>

    <div v-if="!subject" class="card empty">教师登录时需要先选择任教学科。</div>
    <template v-else>
      <div class="card">
        <h3>添加教学资料</h3>
        <div class="form-row">
          <label>资料标题</label>
          <input v-model="title" maxlength="160" placeholder="例如：一次函数图像与性质" />
        </div>
        <div class="form-row">
          <label>来源（选填）</label>
          <input v-model="sourceName" maxlength="200" placeholder="例如：七年级下册教材 / 第三章讲义" />
        </div>
        <div class="form-row">
          <label>资料内容</label>
          <textarea v-model="content" rows="8" maxlength="20000" placeholder="粘贴知识要点、例题解析或评分标准。每条资料单独存储，检索时只会查当前学科的库。" />
          <span class="hint">{{ content.length }} / 20000 字</span>
        </div>
        <div v-if="error" class="error-msg">{{ error }}</div>
        <button class="btn" :disabled="saving || !title.trim() || !content.trim()" @click="save">
          {{ saving ? '正在保存…' : `加入${subjectLabel} Agent 知识库` }}
        </button>
      </div>

      <div class="card">
        <div class="knowledge-head"><h3>{{ subjectLabel }}资料 <span class="count">{{ items.length }}</span></h3><button class="btn ghost small" :disabled="loading" @click="load">刷新</button></div>
        <div v-if="loading" class="loading">加载中…</div>
        <div v-else-if="!items.length" class="empty">这个学科的知识库目前为空。</div>
        <article v-for="item in items" :key="item.id" class="knowledge-item">
          <header><div><b>{{ item.title }}</b><small v-if="item.source_name">来源：{{ item.source_name }}</small></div><button class="btn danger-outline small" @click="remove(item)">删除</button></header>
          <p>{{ item.content }}</p>
        </article>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useTeacherStore } from '../../stores/teacher'
import type { SubjectAgentCode } from '../../api/types'

interface KnowledgeItem { id: number; title: string; content: string; source_name: string | null }
const auth = useAuthStore()
const teacher = useTeacherStore()
const subject = auth.activeSubject as SubjectAgentCode
const labels: Record<string, string> = {
  chinese: '语文', math: '数学', english: '英语', politics: '道法', history: '历史',
  physics: '物理', chemistry: '化学', geography: '地理', biology: '生物'
}
const subjectLabel = computed(() => labels[subject] ?? '学科')
const title = ref('')
const sourceName = ref('')
const content = ref('')
const items = ref<KnowledgeItem[]>([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')

async function load() {
  if (!subject) return
  loading.value = true
  try { items.value = (await teacher.fetchSubjectKnowledge(subject)).items }
  catch (e) { error.value = '知识库读取失败，请确认当前任教学科。'; console.error(e) }
  finally { loading.value = false }
}

async function save() {
  if (!subject || !title.value.trim() || !content.value.trim()) return
  saving.value = true
  error.value = ''
  try {
    await teacher.addSubjectKnowledge(subject, {
      title: title.value.trim(), content: content.value.trim(), source_name: sourceName.value.trim() || undefined
    })
    title.value = ''; sourceName.value = ''; content.value = ''
    await load()
  } catch (e) { error.value = '资料添加失败，请稍后重试。'; console.error(e) }
  finally { saving.value = false }
}

async function remove(item: KnowledgeItem) {
  if (!subject || !window.confirm(`删除「${item.title}」？`)) return
  try { await teacher.deleteSubjectKnowledge(subject, item.id); await load() }
  catch (e) { error.value = '删除失败，请稍后重试。'; console.error(e) }
}

onMounted(load)
</script>

<style scoped>
.form-row textarea { width: 100%; resize: vertical; line-height: 1.65; }
.knowledge-head, .knowledge-item header { display: flex; justify-content: space-between; align-items: center; gap: 14px; }
.knowledge-head h3 { margin: 0; }
.count { color: var(--text-3); font-size: 13px; font-weight: 500; }
.knowledge-item { padding: 15px 0; border-top: 1px solid var(--border); }
.knowledge-item header > div { display: flex; flex-direction: column; gap: 4px; }
.knowledge-item small { color: var(--text-3); }
.knowledge-item p { margin: 10px 0 0; color: var(--text-2); font-size: 13.5px; line-height: 1.7; white-space: pre-wrap; }
</style>
