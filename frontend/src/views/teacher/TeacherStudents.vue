<!-- 教师端：学生列表 —— 进入学生画像的导航页（契约 4.5） -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>学生</h2>
      <p class="page-sub">点击「查看画像」进入某个学生的个人知识轨迹。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <div class="card" v-if="!loading">
      <table class="table" v-if="students.length">
        <thead>
          <tr><th>姓名</th><th>学号</th><th>累计提交</th><th>累计错误</th><th>错误率</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="s in students" :key="s.id">
            <td style="font-weight: 600">{{ s.name }}</td>
            <td class="tnum">{{ s.student_no }}</td>
            <td class="num tnum">{{ s.submission_count }}</td>
            <td class="num tnum">{{ s.error_count }}</td>
            <td class="num tnum">{{ errorRate(s) }}</td>
            <td>
              <router-link :to="`/teacher/students/${s.id}`"><button class="btn small">查看画像</button></router-link>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">暂无学生数据。</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useTeacherStore } from '../../stores/teacher'
import type { StudentSummary } from '../../api/types'

const teacher = useTeacherStore()
const students = ref<StudentSummary[]>([])
const loading = ref(false)
const error = ref('')

// 错误率 = 累计错误 / 累计提交（契约 4.5 口径可直接推导）
function errorRate(s: StudentSummary): string {
  if (!s.submission_count) return '—'
  return `${Math.round((s.error_count / s.submission_count) * 100)}%`
}

onMounted(async () => {
  loading.value = true
  try {
    students.value = await teacher.fetchStudents()
  } catch (e) {
    error.value = '学生列表加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>
