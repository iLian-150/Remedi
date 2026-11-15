<template>
  <section class="card profile-records" aria-labelledby="profile-record-title">
    <h3 id="profile-record-title"><AppIcon name="history" :size="18" /> 学习记录</h3>
    <div v-if="visibleRecords.length" class="record-wrap" tabindex="0" aria-label="学习记录表格">
      <table class="table record-table">
        <thead>
          <tr>
            <th scope="col">时间</th>
            <th scope="col">知识点</th>
            <th scope="col">错因</th>
            <th scope="col">作答步骤</th>
            <th scope="col">订正状态</th>
            <th scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="record in visibleRecords" :key="record.id">
            <td class="record-time tnum">{{ record.created_at.replace('T', ' ').slice(0, 16) }}</td>
            <td>
              <span class="record-subject">{{ getSubjectLabel(record.subject) }}</span>
              <strong>{{ record.knowledge_point || '未归类' }}</strong>
            </td>
            <td>
              <ErrorTypeBadge :type="record.error_type" />
              <span v-if="audience === 'teacher' && record.confidence != null" class="record-subject tnum">置信度 {{ Math.round(record.confidence * 100) }}%</span>
            </td>
            <td class="record-step">
              <span>{{ record.step_text || '—' }}</span>
              <p v-if="audience === 'teacher' && record.detail" class="record-detail">{{ record.detail }}</p>
            </td>
            <td><span class="badge" :class="record.corrected ? 'badge-green' : 'badge-amber'">{{ record.corrected ? '已订正' : '待订正' }}</span></td>
            <td>
              <router-link :to="recordRoute(record)" class="btn small ghost inline-icon record-link">
                {{ audience === 'student' && !record.corrected ? '去订正' : '查看诊断' }} <AppIcon name="chevron-right" :size="14" />
              </router-link>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="empty">暂无错题记录</div>
    <button v-if="visibleCount < records.length" type="button" class="btn small secondary record-more" @click="visibleCount += PAGE_SIZE">
      显示更多记录（{{ records.length - visibleCount }}）
    </button>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import type { GradingError, StudentProfile } from '../api/types'
import { getSubjectLabel } from '../utils/subjectLabels'
import ErrorTypeBadge from './ErrorTypeBadge.vue'
import AppIcon from './icons/AppIcon.vue'

const props = defineProps<{
  profile: StudentProfile
  audience: 'teacher' | 'student'
}>()
type ProfileRecord = StudentProfile['stubborn_errors'][number] & Partial<Pick<GradingError, 'confidence' | 'detail'>>

const records = computed<ProfileRecord[]>(() => {
  const { stubborn_errors: stubborn, recent_errors: recent } = props.profile
  const recentById = new Map(recent.map(record => [record.id, record]))
  const stubbornIds = new Set(stubborn.map(record => record.id))
  const recentOnly = recent.filter(record => !stubbornIds.has(record.id))
  const merged: ProfileRecord[] = []
  let i = 0
  let j = 0
  while (i < stubborn.length && j < recentOnly.length) {
    const left = stubborn[i]
    const right = recentOnly[j]
    const order = left.created_at.localeCompare(right.created_at) || left.id - right.id
    if (order >= 0) {
      merged.push(recentById.get(left.id) ?? left)
      i++
    } else {
      merged.push(right)
      j++
    }
  }
  return merged.concat(stubborn.slice(i).map(record => recentById.get(record.id) ?? record), recentOnly.slice(j))
})
const PAGE_SIZE = 50
const visibleCount = ref(PAGE_SIZE)
const visibleRecords = computed(() => records.value.slice(0, visibleCount.value))

function recordRoute(record: ProfileRecord): RouteLocationRaw {
  if (props.audience === 'teacher') return `/teacher/submissions/${record.id}`
  if (record.corrected) return { path: '/student/diagnosis', query: { submission_id: record.submission_id } }
  return { path: '/student/corrections', query: { error_id: record.id } }
}
</script>

<style scoped>
.record-wrap { overflow-x: auto; }
.record-table { min-width: 680px; }
.record-table td { vertical-align: top; }
.record-time, .record-link { white-space: nowrap; }
.record-time, .record-subject, .record-detail { color: var(--text-2); font-size: 12px; }
.record-subject { display: block; margin: 2px 0; }
.record-step { min-width: 140px; max-width: 360px; white-space: pre-wrap; overflow-wrap: anywhere; }
.record-detail { margin-top: 4px; }
.record-more { display: block; margin: 14px auto 0; }
</style>
