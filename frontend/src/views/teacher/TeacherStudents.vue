<!-- 教师端：学生列表 —— 进入学生画像的导航页（契约 4.5；v0.4.0 改学生卡片网格） -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>学生</h2>
      <p class="page-sub">点击任意学生卡片，进入他的个人知识轨迹。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-if="!loading">
      <div v-if="students.length" class="stu-grid">
        <router-link
          v-for="s in students"
          :key="s.id"
          :to="`/teacher/students/${s.id}`"
          class="card hoverable stu-card"
        >
          <div class="stu-head">
            <span class="stu-avatar">{{ s.name.slice(0, 1) }}</span>
            <div class="stu-id">
              <div class="stu-name">{{ s.name }}</div>
              <div class="stu-no tnum">{{ s.student_no || '—' }}</div>
            </div>
            <AppIcon name="chevron-right" :size="17" class="stu-arrow" />
          </div>
          <div class="stu-stats">
            <div class="stu-stat"><span class="stu-stat-num tnum">{{ s.submission_count }}</span><span class="stu-stat-label">累计提交</span></div>
            <div class="stu-stat"><span class="stu-stat-num tnum err">{{ s.error_count }}</span><span class="stu-stat-label">累计错误</span></div>
            <div class="stu-stat"><span class="stu-stat-num tnum">{{ errorRate(s) }}</span><span class="stu-stat-label">错误率</span></div>
          </div>
          <div class="stu-bar"><span :style="{ width: errorRateWidth(s) }"></span></div>
        </router-link>
      </div>
      <div v-else class="card"><div class="empty">暂无学生数据。</div></div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useTeacherStore } from '../../stores/teacher'
import type { StudentSummary } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'

const teacher = useTeacherStore()
const students = ref<StudentSummary[]>([])
const loading = ref(false)
const error = ref('')

// 错误率 = 累计错误 / 累计提交（契约 4.5 口径可直接推导）
function errorRate(s: StudentSummary): string {
  if (!s.submission_count) return '—'
  return `${Math.round((s.error_count / s.submission_count) * 100)}%`
}
function errorRateWidth(s: StudentSummary): string {
  if (!s.submission_count) return '0%'
  return `${Math.min(100, Math.round((s.error_count / s.submission_count) * 100))}%`
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

<style scoped>
.stu-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.stu-card { margin-bottom: 0; color: var(--text); display: block; }
.stu-head { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.stu-avatar {
  width: 44px; height: 44px; border-radius: 50%; flex-shrink: 0;
  background: var(--primary-50); color: var(--primary);
  font-size: 18px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
}
.stu-id { flex: 1; min-width: 0; }
.stu-name { font-size: 16.5px; font-weight: 700; }
.stu-no { font-size: 12.5px; color: var(--text-3); }
.stu-arrow { color: var(--text-3); }
.stu-stats { display: flex; gap: 10px; }
.stu-stat {
  flex: 1; background: var(--bg); border-radius: 10px; padding: 9px 6px;
  display: flex; flex-direction: column; align-items: center; gap: 1px;
}
.stu-stat-num { font-size: 19px; font-weight: 800; color: var(--primary); line-height: 1.25; }
.stu-stat-num.err { color: var(--red); }
.stu-stat-label { font-size: 12px; color: var(--text-2); }
.stu-bar { height: 6px; background: #EDF0F4; border-radius: 3px; overflow: hidden; margin-top: 12px; }
.stu-bar > span { display: block; height: 100%; background: var(--amber); border-radius: 3px; }
</style>
