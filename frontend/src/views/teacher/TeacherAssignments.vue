<!-- 教师端：作业管理（v0.2.0 新增）
     数据源：GET /api/teacher/assignments（4.8），含每题提交人数。 -->
<template>
  <div class="page">
    <div class="page-head" style="display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap">
      <div>
        <h2>作业管理</h2>
        <p class="page-sub">已发布的作业与每道题的提交情况。</p>
      </div>
      <router-link to="/teacher/assignments/new"><button class="btn inline-icon"><AppIcon name="plus" :size="16" /> 发布新作业</button></router-link>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">作业加载中…</div>

    <div v-for="a in assignments" :key="a.id" class="card">
      <h3>{{ a.title }}</h3>
      <p class="card-sub">{{ fmtTime(a.created_at) }} 发布 · 共 {{ a.questions.length }} 题</p>
      <table class="table">
        <thead>
          <tr><th style="width: 72px">题型</th><th>题干</th><th style="width: 130px">知识点</th><th style="width: 96px">已提交</th></tr>
        </thead>
        <tbody>
          <tr v-for="q in a.questions" :key="q.id">
            <td>
              <span :class="q.type === 'math' ? 'badge badge-blue' : 'badge badge-purple'">{{ q.type === 'math' ? '数学' : '作文' }}</span>
            </td>
            <td>{{ q.prompt }}</td>
            <td>{{ q.knowledge_point }}</td>
            <td class="num tnum">{{ q.submission_count }} 人</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="!loading && !assignments.length" class="card">
      <div class="empty">还没有发布过作业，点右上角「发布新作业」开始布置吧。</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useTeacherStore } from '../../stores/teacher'
import type { TeacherAssignment } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'

const teacher = useTeacherStore()
const assignments = ref<TeacherAssignment[]>([])
const loading = ref(false)
const error = ref('')

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

onMounted(async () => {
  loading.value = true
  try {
    assignments.value = await teacher.fetchTeacherAssignments()
  } catch (e) {
    error.value = '作业列表加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>
