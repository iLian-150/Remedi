<!-- 学生端：作业列表 —— 交作业的统一入口
     数据源：GET /api/student/assignments（契约 3.1）
     点击「开始作答」进入 /student/submit?assignment_id= -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>作业列表</h2>
      <p class="page-sub">选择一份作业开始作答，提交后会立即生成你的诊断报告。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">作业加载中…</div>

    <div v-if="!loading && assignments.length" class="assign-grid">
      <div v-for="a in assignments" :key="a.id" class="card assign-card">
        <h3>{{ a.title }}</h3>
        <p class="assign-desc">{{ a.description || '暂无说明' }}</p>
        <div class="assign-meta">
          <span class="badge badge-blue tnum">{{ a.question_count }} 道题</span>
          <span class="assign-time">{{ fmtTime(a.created_at) }} 发布</span>
        </div>
        <router-link :to="`/student/submit?assignment_id=${a.id}`">
          <button class="btn" style="width: 100%">开始作答</button>
        </router-link>
      </div>
    </div>

    <div v-if="!loading && !assignments.length" class="card">
      <div class="empty">老师还没有布置作业，稍后再来看看吧。</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useStudentStore } from '../../stores/student'
import type { Assignment } from '../../api/types'

const student = useStudentStore()

const assignments = ref<Assignment[]>([])
const loading = ref(false)
const error = ref('')

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

onMounted(async () => {
  loading.value = true
  try {
    assignments.value = await student.fetchAssignments()
  } catch (e) {
    error.value = '作业列表加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>
