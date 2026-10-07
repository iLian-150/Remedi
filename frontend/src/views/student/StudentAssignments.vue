<!-- 学生端：作业列表 —— 交作业的统一入口
     数据源：GET /api/student/assignments（契约 3.1）
     v0.2.1 曾在页内放作业日历；v0.3.0 日历迁至右侧栏；v0.3.1 日历只在本页右栏出现，
     点选日期 → store.assignmentDateFilter 生效 → 本页按发布日期筛选并显示当天完成进度，
     「返回查看全部作业」清掉筛选。点击「开始作答」进入 /student/submit?assignment_id= -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>作业列表</h2>
      <p class="page-sub">选择一份作业开始作答，提交后会立即生成你的诊断报告。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">作业加载中…</div>

    <template v-if="!loading">
      <p class="rail-note"><AppIcon name="calendar" :size="15" /> 作业日历在右侧栏，点选任意一天即可只看当天发布的作业。</p>

      <!-- 日期筛选状态栏（右侧栏日历选中某天时出现） -->
      <div v-if="dateFilter" class="card filter-bar">
        <div class="filter-info">
          <span class="filter-title">{{ dateFilterLabel }} 发布的作业</span>
          <span class="filter-progress-text tnum">已完成 {{ dayProgress.done }} / 共 {{ dayProgress.total }} 份</span>
          <div class="progress-track">
            <div class="progress-fill" :style="{ width: `${dayProgress.total ? (dayProgress.done / dayProgress.total) * 100 : 0}%` }"></div>
          </div>
        </div>
        <button class="btn secondary small" @click="clearFilter">返回查看全部作业</button>
      </div>

      <!-- 作业（全部或按所选日期筛选后） -->
      <div v-if="visibleAssignments.length" class="assign-grid">
        <div v-for="a in visibleAssignments" :key="a.id" class="card assign-card">
          <h3>{{ a.title }}</h3>
          <p class="assign-desc">{{ a.description || '暂无说明' }}</p>
          <p v-if="a.mode === 'offline'" class="assign-offline">
            <AppIcon name="book" :size="14" />
            <span v-if="a.workbook_title">{{ a.workbook_title }}</span>
            <span v-if="a.page_range">{{ a.page_range }}</span>
            <span v-if="a.deadline">截止 {{ fmtTime(a.deadline) }}</span>
          </p>
          <div class="assign-meta">
            <span v-if="a.mode === 'offline'" class="badge badge-amber">线下练习</span>
            <span class="badge badge-blue tnum">{{ a.question_count }} 道题</span>
            <span :class="`badge ${statusBadge(a)}`">{{ statusText(a) }}</span>
            <span class="assign-time">{{ fmtTime(a.created_at) }} 发布</span>
          </div>
          <router-link :to="`/student/submit?assignment_id=${a.id}`">
            <button class="btn" style="width: 100%">开始作答</button>
          </router-link>
        </div>
      </div>

      <div v-else-if="dateFilter" class="card">
        <div class="empty">这一天没有发布的作业，点上方「返回查看全部作业」看全部。</div>
      </div>

      <div v-else-if="!assignments.length" class="card">
        <div class="empty">老师还没有布置作业，稍后再来看看吧。</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useStudentStore } from '../../stores/student'
import type { Assignment } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'

const student = useStudentStore()

const assignments = ref<Assignment[]>([])
const loading = ref(false)
const error = ref('')

/** 右侧栏日历选中的发布日期（yyyy-mm-dd，空 = 不筛选）——与日历共用 store 状态 */
const dateFilter = computed(() => student.assignmentDateFilter)

const visibleAssignments = computed(() =>
  dateFilter.value
    ? assignments.value.filter((a) => a.created_at.slice(0, 10) === dateFilter.value)
    : assignments.value
)

const dateFilterLabel = computed(() => {
  if (!dateFilter.value) return ''
  const [y, m, d] = dateFilter.value.split('-')
  return `${y} 年 ${Number(m)} 月 ${Number(d)} 日`
})

/** 筛选当天（或全部）的完成进度：一份作业的全部题目都提交过 = 已完成 */
const dayProgress = computed(() => {
  const total = visibleAssignments.value.length
  const done = visibleAssignments.value.filter(
    (a) => a.question_count > 0 && doneCount(a) >= a.question_count
  ).length
  return { done, total }
})

function clearFilter() {
  student.setAssignmentDateFilter('')
}

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
.assign-offline {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  font-size: 13px; color: #92400E;
  background: var(--amber-bg); border-radius: 8px;
  padding: 7px 10px; margin-bottom: 10px;
}
.rail-note {
  display: flex; align-items: center; gap: 7px;
  font-size: 13.5px; color: var(--text-2);
  background: var(--primary-50); border: 1px solid #DBEAFE; border-radius: 10px;
  padding: 10px 14px; margin-bottom: 16px;
}
.filter-bar {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  margin-bottom: 16px; padding: 14px 18px;
}
.filter-info { display: flex; align-items: center; gap: 14px; flex: 1; min-width: 240px; flex-wrap: wrap; }
.filter-title { font-size: 15px; font-weight: 700; }
.filter-progress-text { font-size: 13.5px; color: var(--text-2); }
.progress-track {
  flex: 1; min-width: 120px; height: 8px; border-radius: 4px;
  background: var(--bg); overflow: hidden;
}
.progress-fill {
  height: 100%; border-radius: 4px; background: var(--primary);
  transition: width 0.35s ease;
}
@media (prefers-reduced-motion: reduce) {
  .progress-fill { transition: none; }
}
</style>
