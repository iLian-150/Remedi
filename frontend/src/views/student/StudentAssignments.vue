<!-- 学生端：作业列表 —— 交作业的统一入口
     数据源：GET /api/student/assignments（契约 3.1）
     v0.2.1 曾在页内放作业日历；v0.3.0 日历迁至右侧栏（提醒区下方），本页只留一行说明。
     点击「开始作答」进入 /student/submit?assignment_id= -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>作业列表</h2>
      <p class="page-sub">选择一份作业开始作答，提交后会立即生成你的诊断报告。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">作业加载中…</div>

    <template v-if="!loading">
      <p class="rail-note"><AppIcon name="calendar" :size="15" /> 作业日历在右侧栏，点任意一天可以看当天发布的作业和你的批改记录。</p>

      <!-- 全部作业 -->
      <div v-if="assignments.length" class="assign-grid">
        <div v-for="a in assignments" :key="a.id" class="card assign-card">
          <h3>{{ a.title }}</h3>
          <p class="assign-desc">{{ a.description || '暂无说明' }}</p>
          <div class="assign-meta">
            <span class="badge badge-blue tnum">{{ a.question_count }} 道题</span>
            <span :class="`badge ${statusBadge(a)}`">{{ statusText(a) }}</span>
            <span class="assign-time">{{ fmtTime(a.created_at) }} 发布</span>
          </div>
          <router-link :to="`/student/submit?assignment_id=${a.id}`">
            <button class="btn" style="width: 100%">开始作答</button>
          </router-link>
        </div>
      </div>

      <div v-if="!assignments.length" class="card">
        <div class="empty">老师还没有布置作业，稍后再来看看吧。</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useStudentStore } from '../../stores/student'
import type { Assignment } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'

const student = useStudentStore()

const assignments = ref<Assignment[]>([])
const loading = ref(false)
const error = ref('')

/** 每份作业的题目 id 集合（由作业详情拼装，供完成状态展示） */
const questionIdsByAssignment = ref<Record<number, number[]>>({})
const doneQids = ref<Set<number>>(new Set())

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

function doneCount(a: Assignment): number {
  const qids = questionIdsByAssignment.value[a.id] ?? []
  return qids.filter((id) => doneQids.value.has(id)).length
}

function statusText(a: Assignment): string {
  const total = a.question_count
  const done = doneCount(a)
  if (total > 0 && done >= total) return '已完成'
  if (done > 0) return `进行中 ${done}/${total}`
  return '未开始'
}
function statusBadge(a: Assignment): string {
  const total = a.question_count
  const done = doneCount(a)
  if (total > 0 && done >= total) return 'badge-green'
  if (done > 0) return 'badge-amber'
  return 'badge-gray'
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
    const details = await Promise.all(list.map((a) => student.fetchAssignmentDetail(a.id)))
    details.forEach((d) => {
      questionIdsByAssignment.value[d.id] = d.questions.map((q) => q.id)
    })
  } catch (e) {
    error.value = '作业列表加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.rail-note {
  display: flex; align-items: center; gap: 7px;
  font-size: 13.5px; color: var(--text-2);
  background: var(--primary-50); border: 1px solid #DBEAFE; border-radius: 10px;
  padding: 10px 14px; margin-bottom: 16px;
}
</style>
