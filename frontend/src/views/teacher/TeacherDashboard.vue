<!-- 教师端：教学工作台与班级学习概览。
     数据源：教师首页汇总接口（高频错题、知识点错误率、错因分布、学生列表与修复率）
     错因三色全局统一：计算失误=琥珀 / 概念混淆=红 / 审题遗漏=紫 -->
<template>
  <div class="page dashboard-page">
    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-if="!loading">
      <TeachingPlanCard />

      <div class="stat-row kpi-row">
        <div class="stat red"><div class="stat-num tnum">{{ overview.totalErrors }}</div><div class="stat-label">累计错误记录</div></div>
        <div class="stat amber"><div class="stat-num tnum">{{ overview.stubbornErrors }}</div><div class="stat-label">顽固误区</div></div>
        <div class="stat"><div class="stat-num tnum">{{ overview.studentCount }}</div><div class="stat-label">班级学生</div></div>
        <div class="stat green repair-stat">
          <div class="stat-num tnum">{{ Math.round(repairRate.class_repair_rate * 100) }}%</div>
          <div class="stat-label">班级知识修复率</div>
          <div class="repair-bar"><span :style="{ width: `${Math.round(repairRate.class_repair_rate * 100)}%` }"></span></div>
          <div class="repair-sub tnum">已修复 {{ repairRate.fixed_knowledge_point_pairs }} / 出过错 {{ repairRate.total_knowledge_point_pairs }} 个学科知识点组合（按学生计）</div>
        </div>
      </div>

      <!-- 双列：左 知识点错误率 | 右 高频错题 -->
      <div class="dash-grid">
        <div class="card">
          <h3><AppIcon name="target" :size="18" /> 知识点错误率排行</h3>
          <div v-if="kpStats.length" class="kp-cards">
            <div v-for="kp in kpStats" :key="`${kp.subject}:${kp.knowledge_point}`" class="kp-card">
              <div class="kp-card-head">
                <span class="kp-card-name"><span class="badge badge-gray">{{ subjectLabel(kp.subject) }}</span> {{ kp.knowledge_point }}</span>
                <span class="kp-card-rate tnum">{{ Math.round(kp.error_rate * 100) }}%</span>
              </div>
              <div class="kp-card-bar"><span :style="{ width: `${Math.round(kp.error_rate * 100)}%` }"></span></div>
              <p class="kp-card-meta">
                提交 <span class="tnum">{{ kp.submissions }}</span> 次 · 错误 <span class="tnum">{{ kp.errors }}</span> 次
                <template v-if="repairText(kp.subject, kp.knowledge_point)"> · {{ repairText(kp.subject, kp.knowledge_point) }}</template>
              </p>
            </div>
          </div>
          <EChart v-if="kpStats.length" :option="knowledgeOption" />
          <div v-else class="empty">暂无数据。</div>
        </div>

        <div class="card">
          <h3><AppIcon name="alert" :size="18" /> 高频错题 Top{{ topN }}</h3>
          <div class="toolbar">
            <label style="font-size: 14px; color: var(--text-2)">Top N：</label>
            <select v-model="topN" @change="loadTopQuestions" :disabled="topQuestionsLoading" style="width: auto">
              <option :value="5">5</option>
              <option :value="10">10</option>
              <option :value="20">20</option>
            </select>
          </div>
          <div v-if="topQuestionsLoading" class="loading">更新高频错题…</div>
          <div v-else-if="topQuestionsError" class="error-msg">{{ topQuestionsError }}</div>
          <template v-else>
            <EChart v-if="topQuestions.length" :option="topQuestionsOption" />
            <div v-else class="empty">暂无数据。</div>
            <div v-if="topQuestions.length" class="top-list">
              <div v-for="q in topQuestions" :key="q.question_id" class="top-row">
                <span class="top-main">{{ q.stem }}</span>
                <span class="badge badge-gray">{{ subjectLabel(q.subject) }}</span>
                <span class="badge badge-blue">{{ q.knowledge_point }}</span>
                <span class="top-meta tnum">错误 {{ q.error_count }} 次 · {{ q.student_count }} 名学生</span>
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- 底部双列：错因分布 | 需要关注的学生 -->
      <div class="dash-grid">
        <div class="card">
          <h3>错因类型分布</h3>
          <p class="card-sub">基于最近 100 条错误记录统计。</p>
          <EChart v-if="typeOptionData.length" :option="typeOption" />
          <div v-else class="empty">暂无数据。</div>
        </div>

        <div class="card">
          <h3><AppIcon name="users" :size="18" /> 需要你关注的学生</h3>
          <div v-if="!attentionStudents.length" class="empty">暂无需要关注的学生。</div>
          <router-link
            v-for="s in attentionStudents"
            :key="s.id"
            :to="`/teacher/students/${s.id}`"
            class="student-row"
          >
            <span class="student-main">
              <span class="student-name">{{ s.name }}：</span>
              <span class="student-reason">{{ s.reason }}</span>
            </span>
            <AppIcon name="chevron-right" :size="16" />
          </router-link>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useTeacherStore } from '../../stores/teacher'
import type { ClassRepairRate, KnowledgePointStat, StudentAttention, TopQuestion } from '../../api/types'
import { errorTypeKey, ERROR_TYPE_CHART_COLORS } from '../../utils/errorType'
import { getSubjectLabel } from '../../utils/subjectLabels'
import { AsyncEChartBarPie as EChart } from '../../components/AsyncEChart'
import AppIcon from '../../components/icons/AppIcon.vue'
import TeachingPlanCard from '../../components/TeachingPlanCard.vue'

const teacher = useTeacherStore()
const topQuestions = ref<TopQuestion[]>([])
const kpStats = ref<KnowledgePointStat[]>([])
const attentionStudents = ref<StudentAttention[]>([])
const topN = ref(10)
const topQuestionsLoading = ref(false)
const topQuestionsError = ref('')
const loading = ref(false)
const error = ref('')

const overview = reactive({
  totalErrors: 0,
  stubbornErrors: 0,
  studentCount: 0
})
const typeOptionData = ref<Array<{ name: string; value: number }>>([])

// 班级知识修复率（4.11）：KPI 卡 + 各知识点修复率（并入知识点卡片）
const repairRate = ref<ClassRepairRate>({
  class_repair_rate: 0,
  students_with_errors: 0,
  total_knowledge_point_pairs: 0,
  fixed_knowledge_point_pairs: 0,
  knowledge_points: []
})
function subjectLabel(subject: string): string {
  return getSubjectLabel(subject, subject)
}
function repairText(subject: string, kpName: string): string {
  return repairTextByKnowledgePoint.value.get(`${subject}:${kpName}`) ?? ''
}
const repairTextByKnowledgePoint = computed(() => {
  const grouped = new Map<string, string>()
  for (const item of repairRate.value.knowledge_points) {
    grouped.set(
      `${item.subject}:${item.knowledge_point}`,
      `修复率 ${Math.round(item.repair_rate * 100)}%（${item.students_fixed}/${item.students_errored} 名学生）`,
    )
  }
  return grouped
})

const topQuestionsOption = computed(() => {
  // 教师首页汇总接口已按错误数降序，图表直接复用以免再次复制和排序。
  const list = topQuestions.value
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ dataIndex: number }>) => {
        const d = list[params[0].dataIndex]
        return `${subjectLabel(d.subject)} · ${d.stem}<br/>知识点：${d.knowledge_point}<br/>错误 ${d.error_count} 次 · ${d.student_count} 名学生`
      }
    },
    grid: { left: 16, right: 48, top: 16, bottom: 16, containLabel: true },
    xAxis: { type: 'value', name: '错误次数' },
    yAxis: {
      type: 'category',
      data: list.map((d) => `[${subjectLabel(d.subject)}·${d.knowledge_point}] ${d.stem}`),
      axisLabel: { width: 220, overflow: 'truncate', color: '#4B5563' }
    },
    series: [
      {
        type: 'bar',
        data: list.map((d) => d.error_count),
        itemStyle: { color: '#1D4ED8', borderRadius: [0, 6, 6, 0] },
        barWidth: '52%',
        label: { show: true, position: 'right', color: '#6B7280', fontVariantNumeric: 'tabular-nums' }
      }
    ]
  }
})

const knowledgeOption = computed(() => {
  // 知识点排行接口已按错误率降序，沿用接口顺序即可。
  const list = kpStats.value
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ dataIndex: number }>) => {
        const d = list[params[0].dataIndex]
        return `${subjectLabel(d.subject)} · ${d.knowledge_point}<br/>提交 ${d.submissions} 次 · 错误 ${d.errors} 次 · 错误率 ${Math.round(d.error_rate * 100)}%`
      }
    },
    grid: { left: 48, right: 24, top: 24, bottom: 48 },
    xAxis: {
      type: 'category',
      data: list.map((d) => `${subjectLabel(d.subject)}·${d.knowledge_point}`),
      axisLabel: { rotate: 20, color: '#4B5563' }
    },
    yAxis: { type: 'value', name: '错误率', max: 1, axisLabel: { formatter: (v: number) => `${Math.round(v * 100)}%`, color: '#6B7280' } },
    series: [
      {
        type: 'bar',
        data: list.map((d) => d.error_rate),
        itemStyle: { color: '#D97706', borderRadius: [6, 6, 0, 0] },
        barWidth: '48%'
      }
    ]
  }
})

const typeOption = computed(() => ({
  tooltip: { trigger: 'item', valueFormatter: (v: number) => `${v} 次` },
  color: typeOptionData.value.map((d) => ERROR_TYPE_CHART_COLORS[errorTypeKey(d.name)]),
  series: [
    {
      type: 'pie',
      radius: '62%',
      data: typeOptionData.value,
      label: { color: '#4B5563', formatter: '{b}：{c} 次' },
      itemStyle: { borderColor: '#fff', borderWidth: 2 }
    }
  ]
}))

async function loadStats() {
  loading.value = true
  error.value = ''
  try {
    const summary = await teacher.fetchDashboardSummary(topN.value)
    topQuestions.value = summary.top_questions
    kpStats.value = summary.knowledge_points
    attentionStudents.value = summary.attention_students
    if (summary.repair_rate) repairRate.value = summary.repair_rate
    overview.totalErrors = summary.total_errors
    overview.stubbornErrors = summary.stubborn_errors
    overview.studentCount = summary.students.length
    typeOptionData.value = summary.recent_error_types
  } catch (e) {
    error.value = '班级看板加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function loadTopQuestions() {
  topQuestionsLoading.value = true
  topQuestionsError.value = ''
  try {
    topQuestions.value = await teacher.fetchTopQuestions(topN.value)
  } catch (e) {
    topQuestionsError.value = '高频错题加载失败，请稍后重试。'
    console.error(e)
  } finally {
    topQuestionsLoading.value = false
  }
}

onMounted(() => {
  loadStats()
})
</script>

<style scoped>
/* v0.4.0 双列网格：宽屏并排，窄屏堆叠 */
.dash-grid {
  display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr);
  gap: 16px; align-items: start; margin-bottom: 16px;
}
.dashboard-page { max-width: var(--content-frame-width); }
.kpi-row { margin-bottom: 16px; }
.dash-grid > .card { margin-bottom: 0; }
@media (max-width: 1080px) {
  .dash-grid { grid-template-columns: 1fr; }
}
.kpi-row .repair-stat { flex: 1.5 1 200px; }
.repair-bar { height: 7px; background: #EDF0F4; border-radius: 999px; overflow: hidden; margin-top: 9px; }
.repair-bar > span { display: block; height: 100%; background: var(--green); border-radius: 999px; transition: width 0.35s ease; }
.repair-sub { font-size: 12px; color: var(--text-2); margin-top: 6px; }
@media (prefers-reduced-motion: reduce) {
  .repair-bar > span { transition: none; }
}

.kp-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; margin-bottom: 18px; }
.kp-card { background: var(--bg); border-radius: var(--radius-control); padding: 12px 14px; }
.kp-card-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.kp-card-name { font-size: 14.5px; font-weight: 700; }
.kp-card-rate { font-size: 18px; font-weight: 800; color: var(--amber); }
.kp-card-bar { height: 7px; background: #EDF0F4; border-radius: 999px; overflow: hidden; }
.kp-card-bar > span { display: block; height: 100%; background: var(--amber); border-radius: 999px; }
.kp-card-meta { font-size: 12.5px; color: var(--text-2); margin-top: 7px; }

.top-list { margin-top: 14px; border-top: 1px solid #F1F3F6; }
.top-row {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 9px 4px; border-bottom: 1px solid #F1F3F6; font-size: 14px;
}
.top-row:last-child { border-bottom: none; }
.top-main { flex: 1; min-width: 200px; font-weight: 500; }
.top-meta { font-size: 12.5px; color: var(--text-2); }

.student-row {
  display: flex; align-items: center; gap: 12px;
  padding: 11px 6px; border-bottom: 1px solid var(--border); color: var(--text);
}
.student-row:last-child { border-bottom: none; }
.student-row:hover, .student-row:focus-visible { background: var(--primary-50); }
.student-main { flex: 1; min-width: 0; line-height: 1.65; overflow-wrap: anywhere; }
.student-name { font-size: 14.5px; font-weight: 600; }
.student-reason { font-size: 13.5px; color: var(--text-2); }
.student-row > svg { flex-shrink: 0; }
</style>
