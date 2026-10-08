<!-- 教师端：班级总览 Dashboard（v0.4.0 版式重构：KPI 横排 → 双列网格 → 底部双列）
     数据源：4.1 错误列表（总数/顽固数/错因分布）/ 4.3 高频错题 TopN / 4.4 知识点错误率 /
             4.5 学生列表 / 4.11 班级知识修复率（v0.4.0 新增）
     错因三色全局统一：计算失误=琥珀 / 概念混淆=红 / 审题遗漏=紫 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>班级总览</h2>
      <p class="page-sub">一眼看清班级整体的错误分布与高频问题。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-if="!loading">
      <!-- 教学建议（独立加载：失败只隐藏本区，不影响看板主体） -->
      <div v-if="suggestions.length || suggestionsLoaded" class="card suggest-card" style="margin-bottom: 16px">
        <h3><AppIcon name="lightbulb" :size="18" /> 教学建议</h3>
        <p class="card-sub">按班级修复率、知识点错误率、顽固错题与成绩自动生成，供备课参考。</p>
        <div v-if="suggestions.length" class="suggest-list">
          <div v-for="(s, i) in suggestions" :key="i" class="suggest-item">
            <div class="suggest-head">
              <span class="badge" :class="suggestBadgeClass(s.kind)">{{ suggestKindText(s.kind) }}</span>
              <span class="suggest-title">{{ s.title }}</span>
            </div>
            <p class="suggest-evidence tnum">{{ s.evidence }}</p>
            <p class="suggest-action">{{ s.action }}</p>
            <p v-if="s.sample_questions.length" class="suggest-samples">高频错题：{{ s.sample_questions.join('；') }}</p>
          </div>
        </div>
        <div v-else class="empty">暂无建议：各知识点修复情况良好，或数据还不够。</div>
      </div>

      <!-- KPI 指标卡横排（v0.4.0：含新增「班级知识修复率」卡） -->
      <div class="stat-row kpi-row" style="margin-bottom: 16px">
        <div class="stat red"><div class="stat-num tnum">{{ overview.totalErrors }}</div><div class="stat-label">累计错误记录</div></div>
        <div class="stat amber"><div class="stat-num tnum">{{ overview.stubbornErrors }}</div><div class="stat-label">顽固误区</div></div>
        <div class="stat"><div class="stat-num tnum">{{ overview.studentCount }}</div><div class="stat-label">班级学生</div></div>
        <div class="stat green repair-stat">
          <div class="stat-num tnum">{{ Math.round(repairRate.class_repair_rate * 100) }}%</div>
          <div class="stat-label">班级知识修复率</div>
          <div class="repair-bar"><span :style="{ width: `${Math.round(repairRate.class_repair_rate * 100)}%` }"></span></div>
          <div class="repair-sub tnum">已修复 {{ repairRate.fixed_knowledge_point_pairs }} / 出过错 {{ repairRate.total_knowledge_point_pairs }} 个知识点（按学生计）</div>
        </div>
      </div>

      <!-- 科目概览条（原科目总览卡压缩为一行：提交 / 整体错误率 / 涉及知识点） -->
      <div class="subject-strip">
        <span class="strip-subject"><AppIcon name="book" :size="15" /> 数学</span>
        <span>全班提交 <b class="tnum">{{ subjectTotals.submissions }}</b> 次</span>
        <span>整体错误率 <b class="tnum">{{ Math.round(subjectTotals.errorRate * 100) }}%</b></span>
        <span>涉及知识点 <b class="tnum">{{ overview.kpCount }}</b> 个</span>
        <span class="strip-note">修复 = 订正错题后通过二次验证</span>
      </div>

      <!-- 双列：左 知识点错误率 | 右 高频错题 -->
      <div class="dash-grid">
        <div class="card">
          <h3><AppIcon name="target" :size="18" /> 知识点错误率排行</h3>
          <div v-if="kpStats.length" class="kp-cards">
            <div v-for="kp in kpStats" :key="kp.knowledge_point" class="kp-card">
              <div class="kp-card-head">
                <span class="kp-card-name">{{ kp.knowledge_point }}</span>
                <span class="kp-card-rate tnum">{{ Math.round(kp.error_rate * 100) }}%</span>
              </div>
              <div class="kp-card-bar"><span :style="{ width: `${Math.round(kp.error_rate * 100)}%` }"></span></div>
              <p class="kp-card-meta">
                提交 <span class="tnum">{{ kp.submissions }}</span> 次 · 错误 <span class="tnum">{{ kp.errors }}</span> 次
                <template v-if="repairText(kp.knowledge_point)"> · {{ repairText(kp.knowledge_point) }}</template>
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
            <select v-model="topN" @change="loadStats" style="width: auto">
              <option :value="5">5</option>
              <option :value="10">10</option>
              <option :value="20">20</option>
            </select>
          </div>
          <EChart v-if="topQuestions.length" :option="topQuestionsOption" />
          <div v-else class="empty">暂无数据。</div>
          <div v-if="topQuestions.length" class="top-list">
            <div v-for="q in topQuestions" :key="q.question_id" class="top-row">
              <span class="top-main">{{ q.stem }}</span>
              <span class="badge badge-blue">{{ q.knowledge_point }}</span>
              <span class="top-meta tnum">错误 {{ q.error_count }} 次 · {{ q.student_count }} 名学生</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部双列：错因分布 | 学生概览 -->
      <div class="dash-grid">
        <div class="card">
          <h3>错因类型分布</h3>
          <p class="card-sub">基于最近 100 条错误记录统计（契约 4.1 未提供聚合接口，前端本地汇总）。</p>
          <EChart v-if="typeOptionData.length" :option="typeOption" />
          <div v-else class="empty">暂无数据。</div>
        </div>

        <div class="card">
          <h3><AppIcon name="users" :size="18" /> 学生概览</h3>
          <p class="card-sub">点击任意学生，查看他的个人学习画像与错题轨迹。</p>
          <div v-if="!studentsList.length" class="empty">暂无学生数据。</div>
          <router-link
            v-for="s in studentsList"
            :key="s.id"
            :to="`/teacher/students/${s.id}`"
            class="student-row"
          >
            <span class="student-main">
              <span class="student-name">{{ s.name }}</span>
              <span class="student-no">{{ s.student_no || '—' }}</span>
            </span>
            <span class="student-meta tnum">提交 {{ s.submission_count }} 次 · 错误 {{ s.error_count }} 条</span>
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
import type { ClassRepairRate, KnowledgePointStat, StudentSummary, TeachingSuggestion, TopQuestion } from '../../api/types'
import { errorTypeKey, ERROR_TYPE_CHART_COLORS } from '../../utils/errorType'
import EChart from '../../components/EChart.vue'
import AppIcon from '../../components/icons/AppIcon.vue'

const teacher = useTeacherStore()
const topQuestions = ref<TopQuestion[]>([])
const kpStats = ref<KnowledgePointStat[]>([])
const studentsList = ref<StudentSummary[]>([])
const topN = ref(10)
const loading = ref(false)
const error = ref('')

const overview = reactive({ totalErrors: 0, stubbornErrors: 0, studentCount: 0, kpCount: 0 })
const typeOptionData = ref<Array<{ name: string; value: number }>>([])

// 班级知识修复率（4.11）：KPI 卡 + 各知识点修复率（并入知识点卡片）
const repairRate = ref<ClassRepairRate>({
  class_repair_rate: 0,
  students_with_errors: 0,
  total_knowledge_point_pairs: 0,
  fixed_knowledge_point_pairs: 0,
  knowledge_points: []
})
function repairText(kpName: string): string {
  const item = repairRate.value.knowledge_points.find((k) => k.knowledge_point === kpName)
  if (!item) return ''
  return `已修复率 ${Math.round(item.repair_rate * 100)}%（${item.students_fixed}/${item.students_errored} 名学生）`
}

// 教学建议（独立于看板主体加载，失败不报错、不拖垮页面）
const suggestions = ref<TeachingSuggestion[]>([])
const suggestionsLoaded = ref(false)
const SUGGEST_KIND_TEXT: Record<TeachingSuggestion['kind'], string> = {
  reteach: '建议重讲',
  stubborn_group: '分组辅导',
  high_error: '错误率预警',
  low_score: '巩固练习'
}
const SUGGEST_BADGE_CLASS: Record<TeachingSuggestion['kind'], string> = {
  reteach: 'badge-red',
  stubborn_group: 'badge-purple',
  high_error: 'badge-amber',
  low_score: 'badge-blue'
}
function suggestKindText(kind: TeachingSuggestion['kind']): string {
  return SUGGEST_KIND_TEXT[kind] ?? '教学建议'
}
function suggestBadgeClass(kind: TeachingSuggestion['kind']): string {
  return SUGGEST_BADGE_CLASS[kind] ?? 'badge-gray'
}
async function loadSuggestions() {
  try {
    suggestions.value = await teacher.fetchSuggestions()
    suggestionsLoaded.value = true
  } catch (e) {
    console.error(e)
  }
}

// 科目层汇总（数学）：提交总数取知识点排行的提交合计，整体错误率与学生画像同口径（上限 1.0）
const subjectTotals = computed(() => {
  const submissions = kpStats.value.reduce((sum, k) => sum + k.submissions, 0)
  const errorRate = submissions
    ? Math.min(1, overview.totalErrors / submissions)
    : 0
  return { submissions, errorRate }
})

const topQuestionsOption = computed(() => {
  const list = [...topQuestions.value].sort((a, b) => b.error_count - a.error_count)
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ dataIndex: number }>) => {
        const d = list[params[0].dataIndex]
        return `${d.stem}<br/>知识点：${d.knowledge_point}<br/>错误 ${d.error_count} 次 · ${d.student_count} 名学生`
      }
    },
    grid: { left: 16, right: 48, top: 16, bottom: 16, containLabel: true },
    xAxis: { type: 'value', name: '错误次数' },
    yAxis: {
      type: 'category',
      data: list.map((d) => `[${d.knowledge_point}] ${d.stem}`),
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
  const list = [...kpStats.value].sort((a, b) => b.error_rate - a.error_rate)
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ dataIndex: number }>) => {
        const d = list[params[0].dataIndex]
        return `${d.knowledge_point}<br/>提交 ${d.submissions} 次 · 错误 ${d.errors} 次 · 错误率 ${Math.round(d.error_rate * 100)}%`
      }
    },
    grid: { left: 48, right: 24, top: 24, bottom: 48 },
    xAxis: {
      type: 'category',
      data: list.map((d) => d.knowledge_point),
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
    const [tq, kp, errAll, errStubborn, students, repair] = await Promise.all([
      teacher.fetchTopQuestions(topN.value),
      teacher.fetchKnowledgePoints(),
      teacher.fetchErrors({ limit: 1, offset: 0 }),
      teacher.fetchErrors({ limit: 1, offset: 0, stubborn_only: true }),
      teacher.fetchStudents(),
      teacher.fetchRepairRate().catch(() => null)
    ])
    topQuestions.value = tq
    kpStats.value = kp
    studentsList.value = students
    if (repair) repairRate.value = repair
    overview.totalErrors = errAll.total
    overview.stubbornErrors = errStubborn.total
    overview.studentCount = students.length
    overview.kpCount = kp.length

    // 错因类型分布：最近 100 条本地汇总
    const sample = await teacher.fetchErrors({ limit: 100, offset: 0 })
    const counts = new Map<string, number>()
    sample.items.forEach((e) => counts.set(e.error_type, (counts.get(e.error_type) ?? 0) + 1))
    typeOptionData.value = [...counts.entries()].map(([name, value]) => ({ name, value }))
  } catch (e) {
    error.value = '班级看板加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadStats()
  loadSuggestions()
})
</script>

<style scoped>
/* v0.4.0 双列网格：宽屏并排，窄屏堆叠 */
.dash-grid {
  display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr);
  gap: 16px; align-items: start; margin-bottom: 16px;
}
.dash-grid > .card { margin-bottom: 0; }
@media (max-width: 1080px) {
  .dash-grid { grid-template-columns: 1fr; }
}
.kpi-row .repair-stat { flex: 1.5 1 200px; }
.repair-bar { height: 7px; background: #EDF0F4; border-radius: 4px; overflow: hidden; margin-top: 9px; }
.repair-bar > span { display: block; height: 100%; background: var(--green); border-radius: 4px; transition: width 0.35s ease; }
.repair-sub { font-size: 12px; color: var(--text-2); margin-top: 6px; }
.subject-strip {
  display: flex; align-items: center; gap: 18px; flex-wrap: wrap;
  background: var(--card); border: 1px solid #EDF0F4; border-radius: var(--radius);
  box-shadow: var(--shadow); padding: 11px 18px; margin-bottom: 16px;
  font-size: 13.5px; color: var(--text-2);
}
.subject-strip b { color: var(--text); }
.strip-subject { display: inline-flex; align-items: center; gap: 6px; font-weight: 700; color: var(--primary); font-size: 14.5px; }
.strip-note { margin-left: auto; font-size: 12.5px; color: var(--text-3); }
@media (prefers-reduced-motion: reduce) {
  .repair-bar > span { transition: none; }
}

.kp-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; margin-bottom: 18px; }
.kp-card { background: var(--bg); border-radius: 10px; padding: 12px 14px; }
.kp-card-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.kp-card-name { font-size: 14.5px; font-weight: 700; }
.kp-card-rate { font-size: 18px; font-weight: 800; color: var(--amber); }
.kp-card-bar { height: 7px; background: #EDF0F4; border-radius: 4px; overflow: hidden; }
.kp-card-bar > span { display: block; height: 100%; background: var(--amber); border-radius: 4px; }
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
  padding: 11px 6px; border-bottom: 1px solid #F1F3F6; color: var(--text);
}
.student-row:last-child { border-bottom: none; }
.student-row:hover { background: #F8FAFF; }
.student-main { flex: 1; min-width: 0; display: flex; align-items: baseline; gap: 10px; }
.student-name { font-size: 14.5px; font-weight: 600; }
.student-no { font-size: 12.5px; color: var(--text-3); }
.student-meta { font-size: 12.5px; color: var(--text-2); }

.suggest-list { display: flex; flex-direction: column; gap: 12px; }
.suggest-item { background: var(--bg); border-radius: 10px; padding: 12px 14px; }
.suggest-head { display: flex; align-items: center; gap: 9px; margin-bottom: 6px; }
.suggest-title { font-size: 14.5px; font-weight: 700; }
.suggest-evidence { font-size: 13px; color: var(--text); margin: 0 0 4px; }
.suggest-action { font-size: 13.5px; color: var(--text-2); margin: 0; line-height: 1.55; }
.suggest-samples { font-size: 12.5px; color: var(--text-3); margin: 6px 0 0; }
</style>
