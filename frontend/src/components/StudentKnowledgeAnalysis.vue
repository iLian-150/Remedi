<template>
  <section class="card knowledge-analysis" aria-labelledby="profile-knowledge-title">
    <div class="analysis-heading">
      <h3 id="profile-knowledge-title"><AppIcon name="target" :size="18" /> 知识点分析</h3>
      <select v-if="subjects.length > 1" v-model="selectedSubject" aria-label="筛选学科" @change="visibleCount = PAGE_SIZE">
        <option value="">全部学科</option>
        <option v-for="subject in subjects" :key="subject" :value="subject">{{ getSubjectLabel(subject) }}</option>
      </select>
    </div>

    <ul v-if="visiblePoints.length" class="analysis-list">
      <li v-for="{ point, action } in visiblePoints" :key="`${point.subject}:${point.knowledge_point}`" class="analysis-row">
        <div class="point-name">
          <span class="point-subject">{{ getSubjectLabel(point.subject) }}</span>
          <strong>{{ point.knowledge_point || '未归类题目' }}</strong>
        </div>
        <div class="point-evidence">
          <div class="tnum" :title="`已批改 ${point.question_count} 道，出错 ${point.wrong_question_count} 道`">出错 <strong>{{ point.wrong_question_count }} / {{ point.question_count }}</strong> 道</div>
          <div class="point-bar" aria-hidden="true"><span :style="{ width: `${100 * point.wrong_question_count / point.question_count}%` }"></span></div>
          <span v-if="point.review_count" class="point-meta">{{ point.review_count }} 条待核对</span>
        </div>
        <div class="point-patterns">
          <span v-for="pattern in point.patterns.slice(0, 2)" :key="pattern.error_type" class="pattern">
            <ErrorTypeBadge :type="pattern.error_type" />
            <span class="point-meta tnum">{{ pattern.question_count }} 道</span>
          </span>
        </div>
        <div class="point-progress">
          <span v-if="point.status !== 'unclassified'" class="badge" :class="statusLabels[point.status].tone">{{ statusLabels[point.status].text }}</span>
          <span v-if="point.error_count" class="point-meta tnum">{{ point.corrected_count }} / {{ point.error_count }} 条已订正</span>
        </div>
        <router-link v-if="action" :to="action.to" class="btn small ghost inline-icon point-action" :aria-label="`${action.text} ${getSubjectLabel(point.subject)} ${point.knowledge_point || '未归类题目'}`">
          {{ action.text }} <AppIcon name="chevron-right" :size="14" />
        </router-link>
      </li>
    </ul>
    <div v-else class="empty">暂无已批改作答</div>

    <button v-if="visiblePoints.length < filteredPoints.length" type="button" class="btn small secondary analysis-more" @click="visibleCount += PAGE_SIZE">
      显示更多知识点（{{ filteredPoints.length - visiblePoints.length }}）
    </button>

    <details v-if="analysis.error_types.length" class="analysis-distribution" @toggle="onDistributionToggle">
      <summary>全部错因分布</summary>
      <EChart v-if="distributionOpen" :option="distributionOption" style="height: 240px" />
    </details>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import type { ProfileKnowledgeAnalysis, ProfileKnowledgePoint, ProfileKnowledgeStatus } from '../api/types'
import { ERROR_TYPE_CHART_COLORS, errorTypeKey } from '../utils/errorType'
import { getSubjectLabel } from '../utils/subjectLabels'
import { AsyncEChartPie as EChart } from './AsyncEChart'
import ErrorTypeBadge from './ErrorTypeBadge.vue'
import AppIcon from './icons/AppIcon.vue'

const props = defineProps<{ analysis: ProfileKnowledgeAnalysis; audience: 'teacher' | 'student' }>()
const PAGE_SIZE = 8
const selectedSubject = ref('')
const visibleCount = ref(PAGE_SIZE)
const distributionOpen = ref(false)

const subjects = computed(() => [...new Set(props.analysis.points.map(point => point.subject))]
  .sort((a, b) => getSubjectLabel(a).localeCompare(getSubjectLabel(b), 'zh-CN')))
const filteredPoints = computed(() => props.analysis.points.filter(point =>
  !selectedSubject.value || point.subject === selectedSubject.value,
))
const visiblePoints = computed(() => filteredPoints.value.slice(0, visibleCount.value).map(point => ({
  point, action: getAction(point),
})))

const statusLabels = computed<Record<Exclude<ProfileKnowledgeStatus, 'unclassified'>, { text: string; tone: string }>>(() => ({
  stubborn: { text: props.audience === 'teacher' ? '反复出错' : '需要加固', tone: 'badge-red' },
  pending: { text: '待订正', tone: 'badge-amber' },
  needs_review: { text: '待核对', tone: 'badge-gray' },
  awaiting_verify: { text: '待验证', tone: 'badge-blue' },
  fixed: { text: '已修复', tone: 'badge-green' },
  corrected: { text: '已订正', tone: 'badge-green' },
  clear: { text: '未发现错题', tone: 'badge-gray' },
}))

function getAction(point: ProfileKnowledgePoint): { text: string; to: RouteLocationRaw } | null {
  const id = point.next_error_id
  if (id == null) return null
  if (props.audience === 'teacher') return { text: '查看诊断', to: `/teacher/submissions/${id}` }
  if (point.error_count > point.corrected_count) {
    return { text: '去订正', to: { path: '/student/corrections', query: { error_id: id } } }
  }
  if (point.status === 'awaiting_verify') {
    return { text: '去验证', to: { path: '/student/corrections', query: { verify_error_id: id } } }
  }
  return null
}

function onDistributionToggle(event: Event) {
  distributionOpen.value = (event.currentTarget as HTMLDetailsElement).open
}

const distributionOption = computed(() => ({
  tooltip: { trigger: 'item', valueFormatter: (value: number) => `${value} 条` },
  series: [{
    type: 'pie',
    radius: ['34%', '60%'],
    data: props.analysis.error_types.map(({ error_type, count }) => ({
      name: error_type, value: count, itemStyle: { color: ERROR_TYPE_CHART_COLORS[errorTypeKey(error_type)] },
    })),
    label: { formatter: '{b} {c} 条' },
  }],
}))
</script>

<style scoped>
.knowledge-analysis { container-type: inline-size; }
.analysis-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
.analysis-heading h3 { margin: 0; }
.analysis-heading select { width: auto; max-width: 100%; min-height: 38px; padding: 6px 10px; }
.analysis-list { list-style: none; }
.analysis-row {
  display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr) minmax(0, 1.2fr) minmax(0, 1fr) minmax(92px, max-content);
  align-items: center; gap: 14px; padding: 14px 0; border-bottom: 1px solid var(--border);
}
.analysis-row:last-child { border-bottom: 0; }
.point-name, .point-evidence, .point-progress { min-width: 0; display: grid; justify-items: start; gap: 4px; overflow-wrap: anywhere; }
.point-subject, .point-meta { color: var(--text-2); font-size: 12px; }
.point-evidence { font-size: 13px; color: var(--text-strong); }
.point-bar { width: 100%; max-width: 134px; height: 5px; border-radius: var(--radius-pill); background: var(--gray-bg); overflow: hidden; }
.point-bar span { display: block; height: 100%; border-radius: inherit; background: var(--amber); }
.point-patterns { display: grid; justify-items: start; gap: 4px; min-width: 0; }
.pattern { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 6px; }
.pattern .badge, .point-progress .badge { margin-right: 0; }
.pattern .badge { max-width: 100%; white-space: normal; overflow-wrap: anywhere; }
.point-action { justify-self: end; white-space: nowrap; }
.analysis-more { display: block; margin: 12px auto 0; }
.analysis-distribution { margin-top: 12px; border-top: 1px solid var(--border); }
.analysis-distribution summary { width: fit-content; cursor: pointer; padding: 10px 4px 0; color: var(--primary); font-size: 13px; }
@container (max-width: 660px) {
  .analysis-row { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 12px; }
  .point-action { grid-column: 2; }
  .point-patterns:empty { display: none; }
}
@container (max-width: 290px) {
  .analysis-row { grid-template-columns: 1fr; }
  .point-action { grid-column: 1; justify-self: start; }
}
</style>
