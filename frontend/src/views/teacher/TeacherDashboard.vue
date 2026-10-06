<!-- 教师端：班级总览 Dashboard
     数据源：4.1 错误列表（总数/顽固数/错因分布）/ 4.3 高频错题 TopN / 4.4 知识点错误率 / 4.5 学生列表
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
      <!-- 关键指标 -->
      <div class="stat-row" style="margin-bottom: 16px">
        <div class="stat red"><div class="stat-num tnum">{{ overview.totalErrors }}</div><div class="stat-label">累计错误记录</div></div>
        <div class="stat amber"><div class="stat-num tnum">{{ overview.stubbornErrors }}</div><div class="stat-label">顽固误区</div></div>
        <div class="stat"><div class="stat-num tnum">{{ overview.studentCount }}</div><div class="stat-label">班级学生</div></div>
        <div class="stat purple"><div class="stat-num tnum">{{ overview.kpCount }}</div><div class="stat-label">涉及知识点</div></div>
      </div>

      <!-- 一级：科目总览（v0.2.1 分层卡片：科目 → 知识点 → 高频错题 → 学生） -->
      <div class="card">
        <h3><AppIcon name="book" :size="18" /> 科目总览 · 数学</h3>
        <p class="card-sub">当前班级作业均为数学科目，下面按知识点、题目、学生逐层细分。</p>
        <div class="stat-row">
          <div class="stat"><div class="stat-num tnum">{{ subjectTotals.submissions }}</div><div class="stat-label">全班提交（次）</div></div>
          <div class="stat red"><div class="stat-num tnum">{{ overview.totalErrors }}</div><div class="stat-label">累计错误（条）</div></div>
          <div class="stat amber"><div class="stat-num tnum">{{ Math.round(subjectTotals.errorRate * 100) }}%</div><div class="stat-label">整体错误率</div></div>
          <div class="stat purple"><div class="stat-num tnum">{{ overview.kpCount }}</div><div class="stat-label">涉及知识点</div></div>
        </div>
      </div>

      <!-- 二级：知识点错误率（卡片列表 + 图表） -->
      <div class="card">
        <h3><AppIcon name="target" :size="18" /> 知识点错误率排行</h3>
        <div v-if="kpStats.length" class="kp-cards">
          <div v-for="kp in kpStats" :key="kp.knowledge_point" class="kp-card">
            <div class="kp-card-head">
              <span class="kp-card-name">{{ kp.knowledge_point }}</span>
              <span class="kp-card-rate tnum">{{ Math.round(kp.error_rate * 100) }}%</span>
            </div>
            <div class="kp-card-bar"><span :style="{ width: `${Math.round(kp.error_rate * 100)}%` }"></span></div>
            <p class="kp-card-meta">提交 <span class="tnum">{{ kp.submissions }}</span> 次 · 错误 <span class="tnum">{{ kp.errors }}</span> 次</p>
          </div>
        </div>
        <EChart v-if="kpStats.length" :option="knowledgeOption" />
        <div v-else class="empty">暂无数据。</div>
      </div>

      <!-- 三级：高频错题（图表 + 列表） -->
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

      <div class="card">
        <h3>错因类型分布</h3>
        <p class="card-sub">基于最近 100 条错误记录统计（契约 4.1 未提供聚合接口，前端本地汇总）。</p>
        <EChart v-if="typeOptionData.length" :option="typeOption" />
        <div v-else class="empty">暂无数据。</div>
      </div>

      <!-- 四级：学生概览（点进学生画像） -->
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
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useTeacherStore } from '../../stores/teacher'
import type { KnowledgePointStat, StudentSummary, TopQuestion } from '../../api/types'
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
    const [tq, kp, errAll, errStubborn, students] = await Promise.all([
      teacher.fetchTopQuestions(topN.value),
      teacher.fetchKnowledgePoints(),
      teacher.fetchErrors({ limit: 1, offset: 0 }),
      teacher.fetchErrors({ limit: 1, offset: 0, stubborn_only: true }),
      teacher.fetchStudents()
    ])
    topQuestions.value = tq
    kpStats.value = kp
    studentsList.value = students
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

onMounted(loadStats)
</script>

<style scoped>
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
</style>
