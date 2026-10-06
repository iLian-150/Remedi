<!-- 学生端：交作业（v0.2.1 拍照为主；v0.3.0 拍照批改原地完成）
     每道题点「拍照批改」在本页行内展开 PhotoGradeFlow（转写确认 → 诊断卡），不再跳对话页。
     对话页内的拍照批改与简报「去完成」预选保持不变。
     入口：从作业列表进入 /student/submit?assignment_id=；直接访问时下拉选择作业。
     契约：3.1 作业列表 / 3.2 作业详情 / 3.4 我的提交记录（完成状态） -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>交作业</h2>
      <p class="page-sub">选好题目，拍一张作答照片，老师会逐步帮你检查。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-else>
      <div class="card">
        <div v-if="presetAssignment" class="problem-info" style="margin-bottom: 0">
          <p><strong>{{ presetAssignment.title }}</strong></p>
          <p class="kp">{{ presetAssignment.description || '暂无说明' }}</p>
          <p style="margin-top: 8px">
            <router-link to="/student/assignments"><button class="btn small ghost inline-icon"><AppIcon name="chevron-left" :size="14" /> 换一份作业</button></router-link>
          </p>
        </div>
        <div v-else class="form-row" style="margin-bottom: 0">
          <label>选择作业</label>
          <select v-model="assignmentId" @change="onAssignmentChange">
            <option value="">请选择…</option>
            <option v-for="a in assignments" :key="a.id" :value="a.id">
              {{ a.title }}（{{ a.question_count }} 题）
            </option>
          </select>
        </div>
      </div>

      <div v-if="mathQuestions.length" class="card">
        <h3>题目列表</h3>
        <p class="card-sub">点任意一题的「拍照批改」，在本页把作答过程拍下来，老师会逐步批改。</p>
        <div v-for="q in mathQuestions" :key="q.id" class="q-block">
          <div class="q-row">
            <span class="q-order tnum">{{ q.order_num }}</span>
            <div class="q-main">
              <p class="q-stem">{{ q.stem }}</p>
              <p class="q-meta">
                <span class="badge badge-blue">{{ q.knowledge_point }}</span>
                <span v-if="doneQids.has(q.id)" class="badge badge-green">已完成</span>
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
            @graded="doneQids.add(q.id)"
          />
        </div>
      </div>

      <div v-else-if="assignmentId || presetAssignment" class="card">
        <div class="empty">这份作业暂时没有可拍照批改的题目。</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useStudentStore } from '../../stores/student'
import type { Assignment, AssignmentDetail, Question } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'
import PhotoGradeFlow from '../../components/PhotoGradeFlow.vue'

const student = useStudentStore()
const route = useRoute()

const assignments = ref<Assignment[]>([])
const assignmentId = ref<number | ''>('')
const presetAssignment = ref<AssignmentDetail | null>(null) // 从 ?assignment_id= 进入时预置
const questions = ref<Question[]>([])
const doneQids = ref<Set<number>>(new Set())
const expandedQid = ref<number | null>(null)
const loading = ref(false)
const error = ref('')

const mathQuestions = computed(() => questions.value.filter((q) => q.subject === 'math'))

async function loadQuestions(id: number) {
  const detail = await student.fetchAssignmentDetail(id)
  questions.value = detail.questions
  return detail
}

async function onAssignmentChange() {
  questions.value = []
  expandedQid.value = null
  if (!assignmentId.value) return
  try {
    await loadQuestions(Number(assignmentId.value))
  } catch (e) {
    error.value = '作业详情加载失败。'
    console.error(e)
  }
}

function toggleFlow(qid: number) {
  expandedQid.value = expandedQid.value === qid ? null : qid
}

onMounted(async () => {
  loading.value = true
  try {
    const [list, subs] = await Promise.all([
      student.fetchAssignments(),
      student.fetchMySubmissions().catch(() => [])
    ])
    assignments.value = list
    subs.forEach((s) => doneQids.value.add(s.question_id))
    const presetId = Number(route.query.assignment_id)
    if (presetId) {
      try {
        presetAssignment.value = await loadQuestions(presetId)
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
.problem-info { background: var(--primary-50); border-radius: 8px; padding: 12px 16px; font-size: 14px; }
.kp { color: var(--text-2); font-size: 13px; margin-top: 4px; }
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
