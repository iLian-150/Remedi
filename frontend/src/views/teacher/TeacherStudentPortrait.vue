<template>
  <div class="page student-portrait">
    <div class="portrait-toolbar">
      <router-link to="/teacher/students" class="back-link">
        <AppIcon name="chevron-left" :size="16" /> 返回学生
      </router-link>
    </div>

    <div v-if="error" class="error-msg" role="alert">
      {{ error }} <button type="button" class="btn small secondary" @click="loadProfile">重试</button>
    </div>
    <div v-else-if="loading" class="loading" role="status">加载中…</div>

    <template v-else-if="profile">
      <div class="portrait-overview">
        <section class="card identity-card" aria-label="学生信息">
          <div class="identity-avatar" aria-hidden="true">{{ profile.student.name.slice(0, 1) || '学' }}</div>
          <div class="identity-main">
            <h2 class="identity-name">{{ profile.student.name }}</h2>
            <div class="identity-number">
              <span>学号</span>
              <strong class="tnum">{{ profile.student.student_no || '暂无学号' }}</strong>
            </div>
          </div>
        </section>

        <section class="card summary-card" aria-labelledby="portrait-summary-title">
          <h3 id="portrait-summary-title">学习概况</h3>
          <div class="stat-row">
            <div class="stat"><div class="stat-num tnum">{{ profile.knowledge_analysis.graded_question_count }}</div><div class="stat-label">已批改题目</div></div>
            <div class="stat"><div class="stat-num tnum">{{ profile.knowledge_analysis.wrong_question_count }}</div><div class="stat-label">出错题目</div></div>
            <div class="stat amber"><div class="stat-num tnum">{{ profile.knowledge_analysis.pending_correction_count }}</div><div class="stat-label">待订正记录</div></div>
            <div class="stat green"><div class="stat-num tnum">{{ profile.knowledge_analysis.corrected_count }}</div><div class="stat-label">已订正记录</div></div>
          </div>
        </section>
      </div>

      <StudentKnowledgeAnalysis :analysis="profile.knowledge_analysis" audience="teacher" />
      <StudentProfileRecords :profile="profile" audience="teacher" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useTeacherStore } from '../../stores/teacher'
import type { StudentProfile } from '../../api/types'
import StudentKnowledgeAnalysis from '../../components/StudentKnowledgeAnalysis.vue'
import StudentProfileRecords from '../../components/StudentProfileRecords.vue'
import AppIcon from '../../components/icons/AppIcon.vue'

const route = useRoute()
const teacher = useTeacherStore()

const profile = ref<StudentProfile | null>(null)
const loading = ref(true)
const error = ref('')
let loadGeneration = 0

async function loadProfile() {
  const generation = ++loadGeneration
  profile.value = null
  loading.value = true
  error.value = ''
  try {
    const result = await teacher.fetchStudentProfile(Number(route.params.id))
    if (generation === loadGeneration) profile.value = result
  } catch (e) {
    if (generation === loadGeneration) {
      error.value = '学生画像加载失败。'
      console.error(e)
    }
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

watch(() => route.params.id, loadProfile, { immediate: true })
</script>

<style scoped>
.portrait-toolbar { display: flex; align-items: center; margin-bottom: 16px; }
.back-link { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 5px; color: var(--text-2); font-size: 13px; font-weight: 600; white-space: nowrap; }
.back-link:hover { color: var(--primary); }
.portrait-overview { display: grid; grid-template-columns: minmax(240px, 0.95fr) minmax(0, 2.05fr); gap: 16px; align-items: stretch; margin-bottom: 16px; }
.portrait-overview > .card { min-width: 0; margin-bottom: 0; }
.identity-card { display: flex; align-items: center; gap: 20px; padding: clamp(22px, 3vw, 32px); }
.identity-avatar { display: grid; width: 68px; height: 68px; flex: 0 0 auto; place-items: center; border-radius: var(--radius-surface); background: var(--primary-50); color: var(--primary); font-size: 28px; font-weight: 750; }
.identity-main { min-width: 0; }
.identity-name { color: var(--text); font-size: clamp(26px, 3vw, 34px); font-weight: 750; line-height: 1.2; letter-spacing: -0.035em; overflow-wrap: anywhere; }
.identity-number { display: flex; align-items: center; gap: 8px; margin-top: 10px; color: var(--text-2); font-size: 14px; }
.identity-number strong { color: var(--text-strong); font-size: 15px; font-weight: 650; }
.summary-card h3 { margin-bottom: 10px; }
.summary-card .stat-row { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.summary-card .stat { min-width: 0; padding: 12px; }
@media (max-width: 1050px) {
  .portrait-overview { grid-template-columns: 1fr; }
  .identity-card { gap: 16px; }
}
@media (max-width: 520px) {
  .identity-card { align-items: flex-start; gap: 14px; padding: 18px; }
  .identity-avatar { width: 52px; height: 52px; border-radius: var(--radius-control); font-size: 22px; }
  .identity-name { font-size: 25px; }
  .identity-number { flex-wrap: wrap; gap: 4px 8px; font-size: 13px; }
  .identity-number strong { font-size: 14px; overflow-wrap: anywhere; }
  .summary-card .stat-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
