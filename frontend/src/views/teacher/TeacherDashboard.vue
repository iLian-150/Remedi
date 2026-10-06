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

      <div class="card">
        <h3>高频错题 Top{{ topN }}</h3>
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
      </div>

      <div class="card">
        <h3>知识点错误率排行</h3>
        <EChart v-if="kpStats.length" :option="knowledgeOption" />
        <div v-else class="empty">暂无数据。</div>
      </div>

      <div class="card">
        <h3>错因类型分布</h3>
        <p class="card-sub">基于最近 100 条错误记录统计（契约 4.1 未提供聚合接口，前端本地汇总）。</p>
        <EChart v-if="typeOptionData.length" :option="typeOption" />
        <div v-else class="empty">暂无数据。</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useTeacherStore } from '../../stores/teacher'
import type { KnowledgePointStat, TopQuestion } from '../../api/types'
import { errorTypeKey, ERROR_TYPE_CHART_COLORS } from '../../utils/errorType'
import EChart from '../../components/EChart.vue'

const teacher = useTeacherStore()
const topQuestions = ref<TopQuestion[]>([])
const kpStats = ref<KnowledgePointStat[]>([])
const topN = ref(10)
const loading = ref(false)
const error = ref('')

const overview = reactive({ totalErrors: 0, stubbornErrors: 0, studentCount: 0, kpCount: 0 })
const typeOptionData = ref<Array<{ name: string; value: number }>>([])

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
