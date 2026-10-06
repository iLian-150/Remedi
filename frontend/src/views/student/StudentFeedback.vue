<!-- 学生端：诊断报告
     Tab：数学批改 / 作文批改
     数学：分步诊断（首次出错步骤高亮）、错因三色徽标、鼓励性文案
     文案伦理：学生端不出现「顽固误区」「疑似」「置信度」等术语 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>诊断报告</h2>
      <p class="page-sub">看看每一次作答的诊断，错过的知识点一个一个修复。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>

    <div class="card">
      <div class="toolbar" style="margin-bottom: 0">
        <button :class="['btn', 'small', tab === 'math' ? '' : 'secondary']" @click="switchTab('math')">数学批改</button>
        <button :class="['btn', 'small', tab === 'essay' ? '' : 'secondary']" @click="switchTab('essay')">作文批改</button>
      </div>
    </div>

    <!-- 数学 -->
    <template v-if="tab === 'math'">
      <div class="card" v-if="submissions.length">
        <div class="form-row" style="margin-bottom: 0">
          <label>选择一次提交</label>
          <select v-model="selectedSubmissionId" @change="loadMathDetail">
            <option v-for="s in submissions" :key="s.id" :value="s.id">
              {{ s.question_stem }} · {{ s.error_count ? `发现 ${s.error_count} 个问题` : '全部正确' }} · {{ fmtTime(s.submitted_at) }}
            </option>
          </select>
        </div>
      </div>

      <div v-if="mathLoading" class="loading">加载批改结果中…</div>

      <template v-if="mathDetail">
        <div class="card">
          <h3>分步解析 <span class="badge badge-blue">{{ SUBMISSION_STATUS_TEXT[mathDetail.status] ?? mathDetail.status }}</span></h3>
          <div
            v-for="st in mathDetail.steps"
            :key="st.seq"
            class="step"
            :class="{ 'first-error': st.status === 'error', correct: st.status === 'ok' }"
          >
            <div class="step-title">
              {{ st.seq === 0 ? '题干' : `步骤 ${st.seq}` }} · {{ STEP_STATUS_TEXT[st.status] }}
            </div>
            <p>{{ st.text }}</p>
          </div>
        </div>

        <div class="card" v-if="mathDetail.errors.length">
          <h3>发现的问题</h3>
          <p class="card-sub">别灰心，看清楚问题就是进步的开始。</p>
          <div v-for="e in mathDetail.errors" :key="e.id" class="error-item">
            <p>
              <ErrorTypeBadge :type="e.error_type" />
              <span class="badge badge-blue">{{ e.knowledge_point }}</span>
              <span v-if="e.is_stubborn" class="badge badge-amber">需要加固的知识点</span>
              <span v-else class="badge badge-green">已注意，继续保持</span>
            </p>
            <p class="encourage">
              {{ e.is_stubborn ? '这个知识点还需要再加固一下，多练几道同类题会有帮助。' : '这是一次偶发的小失误，下次细心一点就好。' }}
            </p>
            <p class="detail"><strong>解析：</strong>{{ sanitizeStudentCopy(e.detail) }}</p>
            <div class="toolbar" style="margin-top: 8px; margin-bottom: 0">
              <router-link to="/student/corrections"><button class="btn small secondary">去订正这道题</button></router-link>
            </div>
          </div>
        </div>
        <div class="card" v-else>
          <div class="empty">这次全对，继续保持！</div>
        </div>
      </template>

      <div v-if="!mathLoading && !submissions.length" class="card">
        <div class="empty">还没有数学提交，去 <router-link to="/student/assignments" style="color: var(--primary)">作业列表</router-link> 开始第一份作业吧。</div>
      </div>
    </template>

    <!-- 作文 -->
    <template v-if="tab === 'essay'">
      <div class="card" v-if="essays.length">
        <div class="form-row" style="margin-bottom: 0">
          <label>选择一篇作文</label>
          <select v-model="selectedEssayId" @change="loadEssayDetail">
            <option v-for="e in essays" :key="e.essay_id" :value="e.essay_id">
              总分 {{ e.total }} · {{ fmtTime(e.submitted_at) }}
            </option>
          </select>
        </div>
      </div>

      <div v-if="essayLoading" class="loading">加载批改结果中…</div>

      <template v-if="essayDetail">
        <div class="card">
          <h3>五维评分 <span class="badge badge-blue tnum">总分 {{ essayDetail.scores.total }}</span></h3>
          <div class="score-grid">
            <div v-for="(label, key) in scoreLabels" :key="key" class="score-cell">
              <div class="score-num tnum">{{ essayDetail.scores[key as keyof EssayScores] }}</div>
              <div class="score-label">{{ label }}</div>
            </div>
          </div>
          <p style="margin-top: 12px">{{ sanitizeStudentCopy(essayDetail.overall) }}</p>
        </div>

        <div class="card" v-if="essayDetail.grammar_issues?.length">
          <h3>可以改进的句子</h3>
          <p class="card-sub">逐句看看，改完会更好。</p>
          <div v-for="g in essayDetail.grammar_issues" :key="g.sentence_no" class="issue-item">
            <p class="issue-sentence">第 {{ g.sentence_no }} 句：{{ g.sentence }}</p>
            <p>问题：{{ sanitizeStudentCopy(g.issue) }}</p>
            <p class="issue-suggest">建议：{{ sanitizeStudentCopy(g.suggestion) }}</p>
          </div>
        </div>

        <div class="card" v-if="essayDetail.text">
          <h3>我的作文原文</h3>
          <p class="essay-text">{{ essayDetail.text }}</p>
        </div>
      </template>

      <div v-if="!essayLoading && !essays.length" class="card">
        <div class="empty">还没有作文提交，去 <router-link to="/student/assignments" style="color: var(--primary)">作业列表</router-link> 写第一篇吧。</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useStudentStore } from '../../stores/student'
import type { EssayResult, EssayScores, EssaySummary, SubmissionResult, SubmissionSummary } from '../../api/types'
import { STEP_STATUS_TEXT, SUBMISSION_STATUS_TEXT } from '../../api/types'
import { sanitizeStudentCopy } from '../../utils/errorType'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'

const student = useStudentStore()

const tab = ref<'math' | 'essay'>('math')
const error = ref('')

const submissions = ref<SubmissionSummary[]>([])
const selectedSubmissionId = ref<number | ''>('')
const mathDetail = ref<SubmissionResult | null>(null)
const mathLoading = ref(false)

const essays = ref<EssaySummary[]>([])
const selectedEssayId = ref<number | ''>('')
const essayDetail = ref<EssayResult | null>(null)
const essayLoading = ref(false)

const scoreLabels: Record<string, string> = {
  content: '内容',
  structure: '结构',
  grammar: '语法',
  vocabulary: '词汇',
  expression: '表达'
}

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

function switchTab(t: 'math' | 'essay') {
  tab.value = t
  error.value = ''
}

async function loadMathList() {
  try {
    submissions.value = await student.fetchMySubmissions()
    if (submissions.value.length && !selectedSubmissionId.value) {
      selectedSubmissionId.value = submissions.value[0].id
      await loadMathDetail()
    }
  } catch (e) {
    error.value = '提交记录加载失败，请确认后端已启动。'
    console.error(e)
  }
}

async function loadMathDetail() {
  if (!selectedSubmissionId.value) return
  mathLoading.value = true
  mathDetail.value = null
  try {
    mathDetail.value = await student.fetchSubmissionDetail(Number(selectedSubmissionId.value))
  } catch (e) {
    error.value = '批改结果加载失败。'
    console.error(e)
  } finally {
    mathLoading.value = false
  }
}

async function loadEssayList() {
  try {
    essays.value = await student.fetchMyEssays()
    if (essays.value.length && !selectedEssayId.value) {
      selectedEssayId.value = essays.value[0].essay_id
      await loadEssayDetail()
    }
  } catch (e) {
    error.value = '作文列表加载失败。'
    console.error(e)
  }
}

async function loadEssayDetail() {
  if (!selectedEssayId.value) return
  essayLoading.value = true
  essayDetail.value = null
  try {
    essayDetail.value = await student.fetchEssayDetail(Number(selectedEssayId.value))
  } catch (e) {
    error.value = '作文批改结果加载失败。'
    console.error(e)
  } finally {
    essayLoading.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadMathList(), loadEssayList()])
})
</script>

<style scoped>
.error-item { margin-bottom: 16px; padding-bottom: 14px; border-bottom: 1px solid #F1F3F6; }
.error-item:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
.encourage { margin-top: 8px; font-size: 14px; color: var(--text); }
.detail { margin-top: 6px; font-size: 14px; color: var(--text-2); }
.score-grid { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 8px; }
.score-cell { text-align: center; min-width: 84px; background: var(--primary-50); border-radius: 10px; padding: 12px; }
.score-num { font-size: 24px; font-weight: 800; color: var(--primary); }
.score-label { font-size: 12px; color: var(--text-2); }
.issue-item { border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; margin-bottom: 10px; font-size: 14px; }
.issue-sentence { font-weight: 600; margin-bottom: 4px; }
.issue-suggest { color: #065F46; margin-top: 4px; }
.essay-text { white-space: pre-wrap; font-size: 14px; color: var(--text); }
</style>
