<!-- 学生端：交作业（分步录入）
     入口：从作业列表进入 /student/submit?assignment_id=；直接访问 URL 时回退为下拉选择
     流程：1 选择题目 → 2 作答 → 3 查看诊断（数学诊断同步返回）
     契约：3.2 作业详情 / 3.3 数学提交 / 3.6 作文提交 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>交作业</h2>
      <p class="page-sub">一步一步来，写完提交就能看到你的专属诊断报告。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-else>
      <div class="stepper">
        <div class="sp-step done">1 选择题目</div>
        <div class="sp-step" :class="{ done: !!selectedQuestion, current: !submittedOnce && !!selectedQuestion }">2 作答</div>
        <div class="sp-step" :class="{ done: submittedOnce, current: submittedOnce }">3 查看诊断</div>
      </div>

      <!-- 第一步：选择题目 -->
      <div class="card">
        <h3>1 选择题目</h3>
        <div v-if="presetAssignment" class="problem-info">
          <p><strong>{{ presetAssignment.title }}</strong></p>
          <p class="kp">{{ presetAssignment.description }}</p>
          <p style="margin-top: 8px">
            <router-link to="/student/assignments"><button class="btn small ghost inline-icon"><AppIcon name="chevron-left" :size="14" /> 换一份作业</button></router-link>
          </p>
        </div>
        <div v-else class="form-row">
          <label>选择作业</label>
          <select v-model="assignmentId" @change="onAssignmentChange">
            <option value="">请选择…</option>
            <option v-for="a in assignments" :key="a.id" :value="a.id">
              {{ a.title }}（{{ a.question_count }} 题）
            </option>
          </select>
        </div>

        <div class="form-row" v-if="questions.length">
          <label>选择题目</label>
          <select v-model="questionId" @change="resetAnswers">
            <option value="">请选择…</option>
            <option v-for="q in questions" :key="q.id" :value="q.id">
              [{{ q.subject === 'math' ? '数学' : '作文' }} · {{ q.knowledge_point }}] {{ q.stem }}
            </option>
          </select>
        </div>

        <div v-if="selectedQuestion" class="problem-info">
          <p><strong>题面：</strong>{{ selectedQuestion.stem }}</p>
          <p class="kp">知识点：{{ selectedQuestion.knowledge_point }}</p>
        </div>
      </div>

      <!-- 第二步：作答 -->
      <div class="card" v-if="selectedQuestion">
        <h3>2 作答</h3>
        <!-- 数学：有序步骤输入 -->
        <div v-if="selectedQuestion.subject === 'math'" class="form-row">
          <label>作答步骤（按顺序填写，只填作答步骤，不用重复题干）</label>
          <div v-for="(step, i) in steps" :key="i" class="step-input">
            <span class="step-num tnum">步骤 {{ i + 1 }}</span>
            <input v-model="steps[i]" type="text" :placeholder="`例如：第 ${i + 1} 步的解题过程`" />
            <button class="btn small danger" @click="steps.splice(i, 1)" :disabled="steps.length === 1">删除</button>
          </div>
          <button class="btn small secondary" @click="steps.push('')">+ 添加一步</button>
        </div>

        <!-- 作文：大文本框 -->
        <div v-if="selectedQuestion.subject === 'english'" class="form-row">
          <label>我的作文（英文，10~2000 字符）</label>
          <textarea v-model="essayText" rows="10" placeholder="请在此输入英语作文全文…"></textarea>
          <p class="hint">已输入约 {{ essayText.trim().split(/\s+/).filter(Boolean).length }} 个单词</p>
        </div>

        <div class="form-row" style="margin-top: 12px; margin-bottom: 0">
          <button class="btn" :disabled="submitting || !canSubmit" @click="submit">
            {{ submitting ? '批改中，请稍候…' : '提交批改' }}
          </button>
        </div>
      </div>

      <!-- 第三步：诊断结果 -->
      <div v-if="mathResult" class="card">
        <h3>3 诊断报告</h3>
        <p class="card-sub">别灰心，看清楚问题就是进步的开始。</p>
        <h4 class="section-title">分步解析</h4>
        <div
          v-for="st in mathResult.steps"
          :key="st.seq"
          class="step"
          :class="{ 'first-error': st.status === 'error', correct: st.status === 'ok' }"
        >
          <div class="step-title">
            {{ st.seq === 0 ? '题干' : `步骤 ${st.seq}` }} · {{ STEP_STATUS_TEXT[st.status] }}
          </div>
          <p>{{ st.text }}</p>
        </div>

        <template v-if="mathResult.errors.length">
          <h4 class="section-title">发现的问题</h4>
          <div v-for="e in mathResult.errors" :key="e.id" class="error-item">
            <p>
              <ErrorTypeBadge :type="e.error_type" />
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
        </template>
        <div v-else class="empty" style="padding: 24px 0">太棒了，全部正确，继续保持！</div>
      </div>

      <!-- 作文评分结果 -->
      <div v-if="essayResult" class="card">
        <h3>3 作文评分</h3>
        <p class="card-sub">总分 <strong class="tnum" style="font-size: 18px; color: var(--primary)">{{ essayResult.scores.total }}</strong>，看看各维度的表现。</p>
        <div class="score-grid">
          <div v-for="(label, key) in scoreLabels" :key="key" class="score-cell">
            <div class="score-num tnum">{{ essayResult.scores[key as keyof EssayScores] }}</div>
            <div class="score-label">{{ label }}</div>
          </div>
        </div>
        <p style="margin-top: 12px">{{ sanitizeStudentCopy(essayResult.overall) }}</p>
        <div class="toolbar" style="margin-top: 12px; margin-bottom: 0">
          <router-link to="/student/feedback"><button class="btn secondary">查看详细批改</button></router-link>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useStudentStore } from '../../stores/student'
import type { Assignment, AssignmentDetail, EssayResult, Question, SubmissionResult } from '../../api/types'
import { STEP_STATUS_TEXT, type EssayScores } from '../../api/types'
import { sanitizeStudentCopy } from '../../utils/errorType'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import AppIcon from '../../components/icons/AppIcon.vue'

const student = useStudentStore()
const route = useRoute()

const assignments = ref<Assignment[]>([])
const assignmentId = ref<number | ''>('')
const presetAssignment = ref<AssignmentDetail | null>(null) // 从 ?assignment_id= 进入时预置
const questions = ref<Question[]>([])
const questionId = ref<number | ''>('')
const steps = ref<string[]>([''])
const essayText = ref('')
const loading = ref(false)
const submitting = ref(false)
const submittedOnce = ref(false)
const error = ref('')

const mathResult = ref<SubmissionResult | null>(null)
const essayResult = ref<EssayResult | null>(null)

const scoreLabels: Record<string, string> = {
  content: '内容',
  structure: '结构',
  grammar: '语法',
  vocabulary: '词汇',
  expression: '表达'
}

const selectedQuestion = computed(() => questions.value.find((q) => q.id === questionId.value) ?? null)

const canSubmit = computed(() => {
  if (!selectedQuestion.value) return false
  if (selectedQuestion.value.subject === 'math') {
    return steps.value.some((s) => s.trim().length > 0)
  }
  return essayText.value.trim().length >= 10
})

async function loadQuestions(assignmentIdNum: number) {
  const detail = await student.fetchAssignmentDetail(assignmentIdNum)
  questions.value = detail.questions
  return detail
}

async function onAssignmentChange() {
  questionId.value = ''
  questions.value = []
  resetAnswers()
  if (!assignmentId.value) return
  try {
    await loadQuestions(Number(assignmentId.value))
  } catch (e) {
    error.value = '作业详情加载失败。'
    console.error(e)
  }
}

function resetAnswers() {
  steps.value = ['']
  essayText.value = ''
  mathResult.value = null
  essayResult.value = null
  submittedOnce.value = false
}

async function submit() {
  if (!selectedQuestion.value) return
  submitting.value = true
  error.value = ''
  mathResult.value = null
  essayResult.value = null
  try {
    if (selectedQuestion.value.subject === 'math') {
      mathResult.value = await student.submitMath({
        question_id: Number(questionId.value),
        steps: steps.value.filter((s) => s.trim())
      })
    } else {
      essayResult.value = await student.submitEssay({
        question_id: Number(questionId.value),
        text: essayText.value.trim()
      })
    }
    submittedOnce.value = true
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })
  } catch (e: unknown) {
    error.value = '提交失败：' + (errDetail(e) || '请稍后重试。')
    console.error(e)
  } finally {
    submitting.value = false
  }
}

function errDetail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof d === 'string' ? d : ''
}

onMounted(async () => {
  loading.value = true
  try {
    assignments.value = await student.fetchAssignments()
    // 从作业列表进入：?assignment_id= 预置作业与题目
    const presetId = Number(route.query.assignment_id)
    if (presetId) {
      try {
        presetAssignment.value = await loadQuestions(presetId)
        const qid = Number(route.query.question_id)
        if (qid && questions.value.some((q) => q.id === qid)) {
          questionId.value = qid
        }
      } catch {
        error.value = '该作业不存在或已失效，请重新选择。'
      }
    }
  } catch (e) {
    error.value = '作业列表加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.step-input { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.step-num { white-space: nowrap; font-size: 13px; color: var(--text-2); min-width: 52px; }
.problem-info { background: var(--primary-50); border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; font-size: 14px; }
.kp { color: var(--text-2); font-size: 13px; margin-top: 4px; }
.hint { color: var(--text-3); font-size: 12px; margin-top: 4px; }
.section-title { font-size: 15px; margin: 18px 0 10px; }
.error-item { margin-bottom: 16px; padding-bottom: 14px; border-bottom: 1px solid #F1F3F6; }
.error-item:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
.encourage { margin-top: 8px; font-size: 14px; color: var(--text); }
.detail { margin-top: 6px; font-size: 14px; color: var(--text-2); }
.score-grid { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 8px; }
.score-cell { text-align: center; min-width: 84px; background: var(--primary-50); border-radius: 10px; padding: 12px; }
.score-num { font-size: 24px; font-weight: 800; color: var(--primary); }
.score-label { font-size: 12px; color: var(--text-2); }
</style>
