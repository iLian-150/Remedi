<!-- 教师端：学生画像 —— 个人知识轨迹时间线 + 知识点统计
     数据源：GET /api/teacher/students/{student_id}/profile（结构同学生 3.10）
     教师端保留「顽固误区」「疑似分类 / 置信度」等专业表述 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>学生画像</h2>
      <p class="page-sub">纵向追踪一名学生的错误与修复轨迹。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-if="profile">
      <!-- 指标横排（v0.4.0：补「涉及知识点」，四项并排） -->
      <div class="card">
        <h3>{{ profile.student.name }} <span class="badge badge-blue">学号 {{ profile.student.student_no }}</span></h3>
        <div class="stat-row">
          <div class="stat"><div class="stat-num tnum">{{ totalAttempts }}</div><div class="stat-label">累计作答</div></div>
          <div class="stat"><div class="stat-num tnum">{{ totalErrors }}</div><div class="stat-label">累计错误</div></div>
          <div class="stat red"><div class="stat-num tnum">{{ profile.stubborn_errors.length }}</div><div class="stat-label">顽固误区</div></div>
          <div class="stat purple"><div class="stat-num tnum">{{ profile.knowledge_points.length }}</div><div class="stat-label">涉及知识点</div></div>
        </div>
      </div>

      <!-- 双列（v0.4.0）：左 个人知识轨迹 | 右 学习建议 + 知识点错误率图 -->
      <div class="portrait-grid">
        <div class="card">
          <h3>个人知识轨迹</h3>
          <p class="card-sub">按时间倒序：三色圆点 = 错因类型；红色「顽固」标签为需重点跟进的误区。</p>
          <div class="timeline" v-if="allRecords.length">
            <div v-for="r in allRecords" :key="r.id" class="timeline-item">
              <span :class="errorTypeDotClass(r.error_type)"></span>
              <div class="timeline-time tnum">{{ fmtTime(r.created_at) }}</div>
              <div class="timeline-body">
                <p>
                  <ErrorTypeBadge :type="r.error_type" />
                  <span class="badge badge-blue">{{ r.knowledge_point }}</span>
                  <span v-if="r.is_stubborn" class="badge badge-red">顽固误区</span>
                  <span v-else class="badge badge-green">偶发失误</span>
                  <span class="conf-text tnum">置信度 {{ Math.round(r.confidence * 100) }}%</span>
                </p>
                <p class="step-text">{{ r.step_text }}</p>
                <p class="detail">{{ r.detail }}</p>
                <p style="margin-top: 6px">
                  <router-link :to="`/teacher/submissions/${r.id}`"><button class="btn small ghost inline-icon">查看诊断 <AppIcon name="chevron-right" :size="14" /></button></router-link>
                </p>
              </div>
            </div>
          </div>
          <div v-else class="empty">该学生暂无错误记录。</div>
        </div>

        <div class="portrait-side">
          <div class="card" v-if="profile.suggestion">
            <h3>学习建议 <span class="hint" style="font-weight: 400">（模型生成，供教师参考）</span></h3>
            <p class="suggestion">{{ profile.suggestion }}</p>
          </div>

          <div class="card">
            <h3>知识点错误率</h3>
            <EChart v-if="profile.knowledge_points.length" :option="kpOption" />
            <div v-else class="empty">暂无数据。</div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useTeacherStore } from '../../stores/teacher'
import type { StudentProfile } from '../../api/types'
import { errorTypeDotClass } from '../../utils/errorType'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import { AsyncEChartBar as EChart } from '../../components/AsyncEChart'
import AppIcon from '../../components/icons/AppIcon.vue'

const route = useRoute()
const teacher = useTeacherStore()

const profile = ref<StudentProfile | null>(null)
const loading = ref(false)
const error = ref('')

const totalAttempts = computed(() => profile.value?.knowledge_points.reduce((s, k) => s + k.attempts, 0) ?? 0)
const totalErrors = computed(() => profile.value?.knowledge_points.reduce((s, k) => s + k.errors, 0) ?? 0)

// 纵向错误记录：顽固 + 最近错误去重后按时间倒序
const allRecords = computed(() => {
  const map = new Map<number, StudentProfile['recent_errors'][number]>()
  const records = [...(profile.value?.stubborn_errors ?? []), ...(profile.value?.recent_errors ?? [])]
  records.forEach((r) => map.set(r.id, r))
  return [...map.values()].sort((a, b) => b.created_at.localeCompare(a.created_at))
})

// 知识点按错误率降序，供图表与 tooltip 共用
const sortedKps = computed(() =>
  [...(profile.value?.knowledge_points ?? [])].sort((a, b) => b.error_rate - a.error_rate)
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
      itemStyle: { color: '#1D4ED8', borderRadius: [6, 6, 0, 0] },
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
/* v0.4.0 双列：左轨迹时间线 | 右建议+图表，窄屏堆叠 */
.portrait-grid {
  display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr);
  gap: 16px; align-items: start;
}
.portrait-grid > .card { margin-bottom: 0; }
.portrait-side { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.portrait-side > .card { margin-bottom: 0; }
@media (max-width: 1080px) {
  .portrait-grid { grid-template-columns: 1fr; }
}
.suggestion { background: var(--primary-50); border-radius: 8px; padding: 12px 16px; font-size: 14px; }
.step-text { font-weight: 600; margin: 6px 0 4px; }
.detail { color: var(--text-2); font-size: 13px; }
</style>
