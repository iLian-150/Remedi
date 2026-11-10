<!-- 教师端：学生画像 —— 个人知识轨迹时间线 + 知识点统计
     数据源：GET /api/teacher/students/{student_id}/profile（结构同学生 3.10）
     教师端保留「顽固误区」「疑似分类 / 置信度」等专业表述 -->
<template>
  <div class="page student-portrait">
    <div class="portrait-toolbar">
      <router-link to="/teacher/students" class="back-link">
        <AppIcon name="chevron-left" :size="16" /> 返回学生
      </router-link>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-if="profile">
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
            <div class="stat"><div class="stat-num tnum">{{ totalAttempts }}</div><div class="stat-label">累计作答</div></div>
            <div class="stat"><div class="stat-num tnum">{{ totalErrors }}</div><div class="stat-label">累计错误</div></div>
            <div class="stat red"><div class="stat-num tnum">{{ profile.stubborn_errors.length }}</div><div class="stat-label">顽固误区</div></div>
            <div class="stat purple"><div class="stat-num tnum">{{ profile.knowledge_points.length }}</div><div class="stat-label">涉及知识点</div></div>
          </div>
        </section>
      </div>

      <div class="portrait-insights">
        <section class="card knowledge-card" aria-labelledby="portrait-knowledge-title">
          <h3 id="portrait-knowledge-title">知识点错误率</h3>
          <EChart v-if="profile.knowledge_points.length" :option="kpOption" />
          <div v-else class="empty">暂无数据。</div>
        </section>

        <section class="card suggestion-card" aria-labelledby="portrait-suggestion-title">
          <h3 id="portrait-suggestion-title">学习建议</h3>
          <p v-if="profile.suggestion" class="suggestion">{{ profile.suggestion }}</p>
          <div v-else class="empty">暂无建议。</div>
        </section>
      </div>

      <section class="card timeline-card" aria-labelledby="portrait-timeline-title">
        <h3 id="portrait-timeline-title">学习轨迹</h3>
        <div class="timeline" v-if="allRecords.length">
          <div v-for="r in visibleRecords" :key="r.id" class="timeline-item">
            <span :class="errorTypeDotClass(r.error_type)"></span>
            <div class="timeline-time tnum">{{ fmtTime(r.created_at) }}</div>
            <div class="timeline-body">
              <p class="timeline-labels">
                <ErrorTypeBadge :type="r.error_type" />
                <span class="badge badge-blue">{{ r.knowledge_point }}</span>
                <span v-if="r.is_stubborn" class="badge badge-red">顽固误区</span>
                <span v-else class="badge badge-green">偶发失误</span>
                <span v-if="r.confidence != null" class="conf-text tnum">置信度 {{ Math.round(r.confidence * 100) }}%</span>
              </p>
              <p v-if="r.step_text" class="step-text">{{ r.step_text }}</p>
              <p v-if="r.detail" class="detail">{{ r.detail }}</p>
              <p class="timeline-action">
                <router-link :to="`/teacher/submissions/${r.id}`" class="btn small ghost inline-icon">查看诊断 <AppIcon name="chevron-right" :size="14" /></router-link>
              </p>
            </div>
          </div>
        </div>
        <div v-else class="empty">该学生暂无错误记录。</div>
        <button
          v-if="visibleRecords.length < allRecords.length"
          type="button"
          class="btn small secondary portrait-more"
          @click="showMoreRecords"
        >继续显示记录（{{ visibleRecords.length }} / {{ allRecords.length }}）</button>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useTeacherStore } from '../../stores/teacher'
import type { StudentProfile } from '../../api/types'
import { errorTypeDotClass } from '../../utils/errorType'
import { readChartColors } from '../../utils/chartTheme'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import { AsyncEChartBar as EChart } from '../../components/AsyncEChart'
import AppIcon from '../../components/icons/AppIcon.vue'

const route = useRoute()
const chartColors = readChartColors()
const teacher = useTeacherStore()

const profile = ref<StudentProfile | null>(null)
const loading = ref(false)
const error = ref('')

interface PortraitRecord {
  id: number
  knowledge_point: string
  error_type: string
  step_text: string | null
  created_at: string
  is_stubborn: boolean
  confidence?: number
  detail?: string | null
}

const totalAttempts = computed(() => profile.value?.knowledge_points.reduce((s, k) => s + k.attempts, 0) ?? 0)
const totalErrors = computed(() => profile.value?.knowledge_points.reduce((s, k) => s + k.errors, 0) ?? 0)

// 两份后端列表均已按时间倒序，线性合并以避免对全部历史再次排序。
const allRecords = computed<PortraitRecord[]>(() => {
  const stubbornErrors = (profile.value?.stubborn_errors ?? []).map((record) => ({
    ...record,
    is_stubborn: true,
  }))
  const recentErrors = (profile.value?.recent_errors ?? []).map((record) => ({ ...record }))
  const recordsById = new Map<number, PortraitRecord>()
  for (const record of stubbornErrors) recordsById.set(record.id, record)
  const recentOnly: PortraitRecord[] = []
  for (const record of recentErrors) {
    if (!recordsById.has(record.id)) recentOnly.push(record)
    recordsById.set(record.id, record)
  }

  const records: PortraitRecord[] = []
  let stubbornIndex = 0
  let recentIndex = 0
  while (stubbornIndex < stubbornErrors.length || recentIndex < recentOnly.length) {
    const stubbornRecord = stubbornErrors[stubbornIndex]
    const recentRecord = recentOnly[recentIndex]
    if (
      stubbornRecord &&
      (!recentRecord || stubbornRecord.created_at.localeCompare(recentRecord.created_at) >= 0)
    ) {
      records.push(recordsById.get(stubbornRecord.id) ?? stubbornRecord)
      stubbornIndex += 1
    } else if (recentRecord) {
      records.push(recentRecord)
      recentIndex += 1
    }
  }
  return records
})
const RECORD_BATCH_SIZE = 50
const visibleRecordCount = ref(RECORD_BATCH_SIZE)
const visibleRecords = computed(() => allRecords.value.slice(0, visibleRecordCount.value))

function showMoreRecords() {
  visibleRecordCount.value += RECORD_BATCH_SIZE
}

// 学生画像接口已按错误率降序，图表与 tooltip 直接复用接口数组。
const sortedKps = computed(() =>
  profile.value?.knowledge_points ?? []
)

const kpOption = computed(() => ({
  tooltip: {
    trigger: 'axis',
    formatter: (params: Array<{ dataIndex: number }>) => {
      const d = sortedKps.value[params[0].dataIndex]
      return `${d.knowledge_point}<br/>作答 ${d.attempts} 次 · 错误 ${d.errors} 次 · 错误率 ${Math.round(d.error_rate * 100)}%`
    }
  },
  grid: { left: 48, right: 24, top: 24, bottom: 48 },
  xAxis: {
    type: 'category',
    data: sortedKps.value.map((k) => k.knowledge_point),
    axisLabel: { rotate: 20, color: '#4B5563' }
  },
  yAxis: {
    type: 'value',
    name: '错误率',
    max: 1,
    axisLabel: {
      formatter: (v: number) => `${Math.round(v * 100)}%`,
      color: '#6B7280'
    }
  },
  series: [
    {
      type: 'bar',
      data: sortedKps.value.map((k) => k.error_rate),
      itemStyle: { color: chartColors.primary, borderRadius: [chartColors.radiusDetail, chartColors.radiusDetail, 0, 0] },
      barWidth: '48%'
    }
  ]
}))

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

onMounted(async () => {
  loading.value = true
  try {
    profile.value = await teacher.fetchStudentProfile(Number(route.params.id))
  } catch (e) {
    error.value = '学生画像加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})
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
.portrait-insights { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(260px, 0.9fr); gap: 16px; align-items: stretch; margin-bottom: 16px; }
.portrait-insights > .card { min-width: 0; margin-bottom: 0; }
.knowledge-card :deep(.chart), .knowledge-card :deep(canvas) { max-width: 100%; }
.suggestion { min-height: 120px; padding: 16px; border-radius: var(--radius-control); background: var(--primary-50); color: var(--text-strong); font-size: 14px; overflow-wrap: anywhere; }
.timeline-card { min-width: 0; }
.timeline-labels { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 0; }
.timeline-labels .badge { margin-bottom: 4px; }
.timeline-action { margin-top: 6px; }
.step-text { font-weight: 600; margin: 6px 0 4px; }
.detail { color: var(--text-2); font-size: 13px; }
.portrait-more { display: block; margin: 14px auto 0; }
@media (max-width: 900px) {
  .portrait-overview { grid-template-columns: 1fr; }
  .portrait-insights { grid-template-columns: 1fr; }
  .identity-card { gap: 16px; }
}
@media (max-width: 520px) {
  .identity-card { align-items: flex-start; gap: 14px; padding: 18px; }
  .identity-avatar { width: 52px; height: 52px; border-radius: var(--radius-control); font-size: 22px; }
  .identity-name { font-size: 25px; }
  .identity-number { flex-wrap: wrap; gap: 4px 8px; font-size: 13px; }
  .identity-number strong { font-size: 14px; overflow-wrap: anywhere; }
  .summary-card .stat-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  .summary-card .stat { min-width: 0; }
}
</style>
