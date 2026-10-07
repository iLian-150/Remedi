<!-- 学生端：交作业（v0.2.1 拍照为主；v0.3.0 拍照批改原地完成；v0.6.0 一键直达）
     每道题点「拍照批改」在本页行内展开 PhotoGradeFlow 的 direct 模式：
     选完照片自动转写并立刻出结果卡，不跳任何下一级页面（组件内原地展开/原地出结果，
     全程无路由跳转）。对话页内的拍照批改与简报「去完成」预选保持确认模式不变。
     v0.9.0：作业切换改成页面顶部一条独立 sticky 切换条（下拉选作业，原地切换，
     与下方题目列表视觉分开，不再混在题目卡里）；新批改先过老师审核——
     提交后题目状态显示「待老师审核」，审核通过后诊断才可见（PhotoGradeFlow 出状态卡）。
     入口：从作业列表进入 /student/submit?assignment_id=；直接访问时用切换条选择。
     契约：3.1 作业列表 / 3.2 作业详情 / 3.4 我的提交记录（完成状态含 review_status） -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>交作业</h2>
      <p class="page-sub">选好题目，拍一张作答照片；老师审核后就能看到逐步批改。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-else>
      <!-- 作业切换条（v0.9.0）：钉在页面顶部，与题目列表分开 -->
      <div class="card switch-bar">
        <label class="switch-label" for="submit-assignment-select">
          <AppIcon name="clipboard" :size="16" /> 正在交的作业
        </label>
        <select id="submit-assignment-select" v-model="assignmentId" class="switch-select" @change="onAssignmentChange">
          <option value="">请选择一份作业…</option>
          <option v-for="a in assignments" :key="a.id" :value="a.id">
            {{ a.title }}（{{ a.question_count }} 题）{{ a.mode === 'offline' ? ' · 线下练习' : '' }}
          </option>
        </select>
        <router-link to="/student/assignments" class="switch-all">全部作业 <AppIcon name="chevron-right" :size="13" /></router-link>
      </div>

      <!-- 当前作业说明（与切换条分开的独立信息卡） -->
      <div v-if="currentDetail" class="card assign-info">
        <p>
          <strong>{{ currentDetail.title }}</strong>
          <span v-if="currentDetail.mode === 'offline'" class="badge badge-amber" style="margin-left: 8px">线下练习</span>
        </p>
        <p class="kp">{{ currentDetail.description || '暂无说明' }}</p>
        <p v-if="currentDetail.mode === 'offline'" class="kp" style="margin-top: 4px">
          <template v-if="currentDetail.workbook_title">{{ currentDetail.workbook_title }}</template>
          <template v-if="currentDetail.page_range"> · {{ currentDetail.page_range }}</template>
          <template v-if="currentDetail.deadline"> · 截止 {{ currentDetail.deadline.replace('T', ' ').slice(0, 16) }}</template>
          —— 在练习册上做完后，逐题拍照提交就可以啦。
        </p>
      </div>

      <div v-if="mathQuestions.length" class="card">
        <h3>题目列表</h3>
        <p class="card-sub">点任意一题的「拍照批改」，就在本题这里把作答过程拍下来，不用跳页面。</p>
        <div v-for="q in mathQuestions" :key="q.id" class="q-block">
          <div class="q-row">
            <span class="q-order tnum">{{ q.order_num }}</span>
            <div class="q-main">
              <p class="q-stem">{{ q.stem }}</p>
              <p class="q-meta">
                <span class="badge badge-blue">{{ q.knowledge_point }}</span>
                <span v-if="pendingQids.has(q.id)" class="badge badge-amber">待老师审核</span>
                <span v-else-if="doneQids.has(q.id)" class="badge badge-green">已完成</span>
                <span v-else class="badge badge-gray">未完成</span>
              </p>
            </div>
            <button class="btn inline-icon" @click="toggleFlow(q.id)">
              <AppIcon name="camera" :size="16" />
              {{ expandedQid === q.id ? '收起' : '拍照批改' }}
            </button>
          </div>
          <PhotoGradeFlow
            v-if="expandedQid === q.id"
            :question-id="q.id"
            :question-stem="q.stem"
            direct
            @graded="onGraded(q.id, $event)"
          />
        </div>
      </div>

      <div v-else-if="assignmentId" class="card">
        <div class="empty">这份作业暂时没有可拍照批改的题目。</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStudentStore } from '../../stores/student'
import type { Assignment, AssignmentDetail, Question, SubmissionResult } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'
import PhotoGradeFlow from '../../components/PhotoGradeFlow.vue'

const student = useStudentStore()
const route = useRoute()
const router = useRouter()

const assignments = ref<Assignment[]>([])
const assignmentId = ref<number | ''>('')
const currentDetail = ref<AssignmentDetail | null>(null) // 当前所选作业详情（说明卡 + 题目来源）
const questions = ref<Question[]>([])
const doneQids = ref<Set<number>>(new Set())
const pendingQids = ref<Set<number>>(new Set()) // v0.9.0：最新一次提交在等老师审核的题目
const expandedQid = ref<number | null>(null)
const loading = ref(false)
const error = ref('')

const mathQuestions = computed(() => questions.value.filter((q) => q.subject === 'math'))

async function loadQuestions(id: number) {
  const detail = await student.fetchAssignmentDetail(id)
  questions.value = detail.questions
  currentDetail.value = detail
  return detail
}

async function selectAssignment(id: number) {
  questions.value = []
  currentDetail.value = null
  expandedQid.value = null
  if (!id) return
  try {
    await loadQuestions(id)
  } catch (e) {
    error.value = '作业详情加载失败。'
    console.error(e)
  }
}

async function onAssignmentChange() {
  const id = Number(assignmentId.value)
  // 地址栏同步当前作业，刷新/分享链接都落回这份作业
  router.replace({ query: id ? { assignment_id: id } : {} })
  await selectAssignment(id)
}

function toggleFlow(qid: number) {
  expandedQid.value = expandedQid.value === qid ? null : qid
}

/** 批改完成（v0.9.0）：新提交先过老师审核——pending 进待审核集，否则进已完成集 */
function onGraded(qid: number, result: SubmissionResult) {
  if (result.status === 'pending_review' || result.review_status === 'pending') {
    pendingQids.value = new Set(pendingQids.value).add(qid)
    doneQids.value = new Set([...doneQids.value].filter((x) => x !== qid))
  } else {
    doneQids.value = new Set(doneQids.value).add(qid)
    pendingQids.value = new Set([...pendingQids.value].filter((x) => x !== qid))
  }
}

onMounted(async () => {
  loading.value = true
  try {
    const [list, subs] = await Promise.all([
      student.fetchAssignments(),
      student.fetchMySubmissions().catch(() => [])
    ])
    assignments.value = list
    // 每道题取最新一次提交定状态（列表按时间倒序，首见即最新）
    const latestByQid = new Map<number, string>()
    subs.forEach((s) => {
      if (!latestByQid.has(s.question_id)) {
        latestByQid.set(s.question_id, s.review_status ?? 'approved')
      }
    })
    latestByQid.forEach((rstatus, qid) => {
      if (rstatus === 'pending') pendingQids.value.add(qid)
      else doneQids.value.add(qid)
    })
    const presetId = Number(route.query.assignment_id)
    if (presetId && list.some((a) => a.id === presetId)) {
      assignmentId.value = presetId
      try {
        await loadQuestions(presetId)
      } catch {
        error.value = '该作业不存在或已失效，请重新选择。'
      }
    } else if (presetId) {
      error.value = '该作业不存在或已失效，请重新选择。'
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
/* 作业切换条（v0.9.0）：sticky 钉顶，与下方卡片拉开间距和层级 */
.switch-bar {
  position: sticky;
  top: 12px;
  z-index: 60;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px 18px;
  box-shadow: var(--shadow-md);
}
.switch-label {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  white-space: nowrap;
}
.switch-select { flex: 1; min-width: 200px; width: auto; }
.switch-all {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--primary);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}
@media (max-width: 960px) {
  /* 移动端顶栏高 52px，切换条贴在它下方 */
  .switch-bar { top: 60px; }
}
.assign-info { background: var(--primary-50); border-color: #DBEAFE; box-shadow: none; }
.assign-info .kp { color: var(--text-2); font-size: 13px; margin-top: 4px; }
.q-block { border-bottom: 1px solid #F1F3F6; padding-bottom: 12px; }
.q-block:last-child { border-bottom: none; padding-bottom: 0; }
.q-row {
  display: flex; align-items: center; gap: 14px;
  padding: 12px 4px 0;
}
.q-order {
  width: 28px; height: 28px; border-radius: 50%; flex-shrink: 0;
  background: var(--primary-50); color: var(--primary);
  font-weight: 700; font-size: 13.5px;
  display: flex; align-items: center; justify-content: center;
}
.q-main { flex: 1; min-width: 0; }
.q-stem { font-size: 14.5px; font-weight: 500; }
.q-meta { margin-top: 4px; }
</style>
