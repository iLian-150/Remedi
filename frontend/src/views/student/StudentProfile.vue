<!-- 学生端：我的档案
     核心视觉：错误轨迹时间线 —— 三色圆点展示历次错误，修复状态为「已修复 / 加固中」
     文案伦理：学生端用「需要加固的知识点」「已修复」「继续保持」，不出现贴标签术语
     修复状态口径（最小假设，契约无订正记录查询接口）：
       已修复 = 本机提交订正且判定正确；其余 = 加固中 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>我的档案</h2>
      <p class="page-sub">记录你的每一次进步：错过的知识点，一个一个修复。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-if="profile">
      <div class="card">
        <h3>{{ profile.student.name }} <span class="badge badge-blue">学号 {{ profile.student.student_no }}</span></h3>
        <div class="stat-row">
          <div class="stat"><div class="stat-num tnum">{{ totalAttempts }}</div><div class="stat-label">累计作答</div></div>
          <div class="stat"><div class="stat-num tnum">{{ totalErrors }}</div><div class="stat-label">累计发现问题</div></div>
          <div class="stat amber"><div class="stat-num tnum">{{ reinforcingCount }}</div><div class="stat-label">加固中</div></div>
          <div class="stat green"><div class="stat-num tnum">{{ fixedIds.size }}</div><div class="stat-label">已修复</div></div>
        </div>
      </div>

      <div class="card" v-if="profile.suggestion">
        <h3>给你的学习建议</h3>
        <p class="suggestion">{{ sanitizeStudentCopy(profile.suggestion) }}</p>
      </div>

      <!-- 核心视觉：错误轨迹时间线 -->
      <div class="card">
        <h3>我的错误轨迹</h3>
        <p class="card-sub">每一次错误都是一次学习机会，看看它们是如何被逐个修复的。</p>
        <div class="timeline" v-if="timeline.length">
          <div v-for="e in timeline" :key="e.id" class="timeline-item">
            <span :class="errorTypeDotClass(e.error_type)"></span>
            <div class="timeline-time tnum">{{ fmtTime(e.created_at) }}</div>
            <div class="timeline-body">
              <p>
                <ErrorTypeBadge :type="e.error_type" />
                <span class="badge badge-blue">{{ e.knowledge_point }}</span>
                <span v-if="fixedIds.has(e.id)" class="badge badge-green">已修复</span>
                <span v-else class="badge badge-amber">加固中</span>
              </p>
              <p class="step-text">{{ e.step_text }}</p>
              <p class="detail">{{ sanitizeStudentCopy(e.detail) }}</p>
              <p v-if="!fixedIds.has(e.id)" style="margin-top: 6px">
                <router-link to="/student/corrections"><button class="btn small ghost inline-icon">去订正 <AppIcon name="chevron-right" :size="14" /></button></router-link>
              </p>
            </div>
          </div>
        </div>
        <div v-else class="empty">还没有错误记录，继续保持！</div>
      </div>

      <div class="card">
        <h3>知识点掌握度</h3>
        <p class="card-sub">掌握度 = 1 − 错误率，越高越好。</p>
        <EChart v-if="profile.knowledge_points.length" :option="masteryOption" />
        <div v-else class="empty">暂无数据。</div>
      </div>

      <div class="card">
        <h3>问题类型分布</h3>
        <EChart v-if="typeOptionData.length" :option="typeOption" />
        <div v-else class="empty">暂无数据。</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useStudentStore } from '../../stores/student'
import { useAuthStore } from '../../stores/auth'
import type { GradingError, StudentProfile } from '../../api/types'
import { errorTypeDotClass, errorTypePalette, sanitizeStudentCopy } from '../../utils/errorType'
import { getFixedErrorIds } from '../../utils/correctionTracker'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import EChart from '../../components/EChart.vue'
import AppIcon from '../../components/icons/AppIcon.vue'

const student = useStudentStore()
const auth = useAuthStore()
const profile = ref<StudentProfile | null>(null)
const loading = ref(false)
const error = ref('')
const fixedIds = ref<Set<number>>(new Set())

const totalAttempts = computed(() => profile.value?.knowledge_points.reduce((s, k) => s + k.attempts, 0) ?? 0)
const totalErrors = computed(() => profile.value?.knowledge_points.reduce((s, k) => s + k.errors, 0) ?? 0)

// 错误轨迹：顽固 + 最近错误去重，按时间倒序
const timeline = computed(() => {
  const map = new Map<number, GradingError>()
  ;[...(profile.value?.stubborn_errors ?? []), ...(profile.value?.recent_errors ?? [])].forEach((e) => map.set(e.id, e))
  return [...map.values()].sort((a, b) => b.created_at.localeCompare(a.created_at))
})

const reinforcingCount = computed(() => timeline.value.filter((e) => !fixedIds.value.has(e.id)).length)

// 问题类型分布：三色统一
const typeOptionData = computed(() => {
  const counts = new Map<string, number>()
  timeline.value.forEach((e) => counts.set(e.error_type, (counts.get(e.error_type) ?? 0) + 1))
  return [...counts.entries()].map(([name, value]) => ({ name, value }))
})

const masteryOption = computed(() => ({
  tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${Math.round(v * 100)}%` },
  grid: { left: 48, right: 24, top: 24, bottom: 48 },
  xAxis: {
    type: 'category',
    data: (profile.value?.knowledge_points ?? []).map((k) => k.knowledge_point),
    axisLabel: { rotate: 20, color: '#6B7280' }
  },
  yAxis: { type: 'value', max: 1, axisLabel: { formatter: (v: number) => `${Math.round(v * 100)}%`, color: '#6B7280' } },
  series: [
    {
      type: 'bar',
      data: (profile.value?.knowledge_points ?? []).map((k) => k.mastery),
      itemStyle: { color: '#1D4ED8', borderRadius: [6, 6, 0, 0] },
      barWidth: '48%'
    }
  ]
}))

const typeOption = computed(() => ({
  tooltip: { trigger: 'item', valueFormatter: (v: number) => `${v} 次` },
  color: errorTypePalette(),
  series: [
    {
      type: 'pie',
      radius: '62%',
      data: typeOptionData.value,
      label: { color: '#4B5563' },
      itemStyle: { borderColor: '#fff', borderWidth: 2 }
    }
  ]
}))

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

onMounted(async () => {
  loading.value = true
  try {
    if (auth.user) fixedIds.value = getFixedErrorIds(auth.user.id)
    profile.value = await student.fetchProfile()
  } catch (e) {
    error.value = '档案加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.suggestion { background: var(--primary-50); border-radius: 8px; padding: 12px 16px; font-size: 14px; }
.step-text { font-weight: 600; margin: 6px 0 4px; }
.detail { color: var(--text-2); font-size: 13px; }
</style>
