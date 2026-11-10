<!-- 学生端：我的档案。概览、掌握度和记录沿用全站卡片与状态色。
     文案伦理：学生端用「需要加固的知识点」「已订正」「继续保持」，不出现贴标签术语；
     「已订正」口径 = 本机提交订正且判定正确；知识点「已修复」以学习报告为准。 -->
<template>
  <div class="page">
    <div class="page-head profile-page-head">
      <router-link to="/student/report" class="btn small secondary inline-icon profile-report-link">
        <AppIcon name="chart" :size="15" /> 学习报告
      </router-link>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-if="profile">
      <section class="profile-summary-card">
        <div class="profile-summary">
          <div class="profile-identity">
            <div class="profile-name">{{ profile.student.name }}</div>
            <p class="profile-meta">
              学号 <span class="tnum">{{ profile.student.student_no || '—' }}</span>
              · 身份 学生
              <template v-if="profile.student.created_at">
                · {{ fmtDate(profile.student.created_at) }} 来到 Remedi
              </template>
            </p>
          </div>

          <div class="profile-divider"></div>

          <div class="profile-stats">
            <div class="profile-stat">
              <div class="profile-stat-num tnum">{{ totalAttempts }}</div>
              <div class="profile-stat-label">累计作答</div>
            </div>
            <div class="profile-stat">
              <div class="profile-stat-num tnum">{{ totalErrors }}</div>
              <div class="profile-stat-label">累计发现问题</div>
            </div>
            <div class="profile-stat">
              <div class="profile-stat-num profile-amber tnum">{{ reinforcingCount }}</div>
              <div class="profile-stat-label">加固中</div>
            </div>
            <div class="profile-stat">
              <div class="profile-stat-num profile-green tnum">{{ fixedIds.size }}</div>
              <div class="profile-stat-label">已订正错题</div>
            </div>
          </div>

          <div class="profile-mastery" v-if="profile.knowledge_points.length">
            <p class="profile-section-title">知识点掌握度</p>
            <div v-for="k in profile.knowledge_points" :key="k.knowledge_point" class="mastery-row">
              <span class="mastery-point">{{ k.knowledge_point }}</span>
              <span class="mastery-track">
                <span
                  class="mastery-fill"
                  :class="masteryTone(k.mastery)"
                  :style="{ width: `${Math.max(4, Math.round(k.mastery * 100))}%` }"
                ></span>
              </span>
              <span class="mastery-percent tnum">{{ Math.round(k.mastery * 100) }}%</span>
            </div>
          </div>
          <p v-else class="profile-muted profile-empty">暂无作答记录。</p>

          <div class="profile-message" v-if="profile.suggestion">
            <p class="profile-message-label">老师寄语</p>
            <p class="profile-message-text">{{ sanitizeStudentCopy(profile.suggestion) }}</p>
          </div>
        </div>
      </section>

      <!-- ================= 成长记录表（课表式网格） ================= -->
      <div class="card">
        <h3>成长记录表</h3>
        <div v-if="timeline.length" class="record-wrap">
          <table class="record-table">
            <thead>
              <tr><th>时间</th><th>知识点</th><th>问题类型</th><th>出错的步骤</th><th>状态</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="e in visibleTimeline" :key="e.id">
                <td class="tnum record-time">{{ fmtTime(e.created_at) }}</td>
                <td><span class="badge badge-blue">{{ e.knowledge_point }}</span></td>
                <td><ErrorTypeBadge :type="e.error_type" /></td>
                <td class="record-step">{{ e.step_text }}</td>
                <td>
                  <span v-if="fixedIds.has(e.id)" class="badge badge-green">已订正</span>
                  <span v-else class="badge badge-amber">加固中</span>
                </td>
                <td>
                  <router-link v-if="!fixedIds.has(e.id)" to="/student/corrections" class="btn small ghost inline-icon">
                    去订正 <AppIcon name="chevron-right" :size="14" />
                  </router-link>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty">暂无错误记录。</div>
        <button
          v-if="visibleTimeline.length < timeline.length"
          type="button"
          class="btn small secondary profile-more"
          @click="showMoreTimeline"
        >继续显示记录（{{ visibleTimeline.length }} / {{ timeline.length }}）</button>
      </div>

      <!-- 问题类型分布 -->
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
import type { StudentProfile } from '../../api/types'
import { errorTypePalette, sanitizeStudentCopy } from '../../utils/errorType'
import { getFixedErrorIds } from '../../utils/correctionTracker'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import { AsyncEChartPie as EChart } from '../../components/AsyncEChart'
import AppIcon from '../../components/icons/AppIcon.vue'

const student = useStudentStore()
const auth = useAuthStore()
const profile = ref<StudentProfile | null>(null)
const loading = ref(false)
const error = ref('')
const fixedIds = ref<Set<number>>(new Set())
type ProfileErrorRecord = StudentProfile['stubborn_errors'][number] | StudentProfile['recent_errors'][number]

// 一次汇总档案页的总量、去重时间线与问题类型，避免模板分别重复扫描。
const profileSummary = computed(() => {
  let totalAttempts = 0
  let totalErrors = 0
  for (const item of profile.value?.knowledge_points ?? []) {
    totalAttempts += item.attempts
    totalErrors += item.errors
  }

  // 两份后端列表都已按时间倒序；合并而非对全量历史重新排序。
  // 最近错误沿用原优先级：同 ID 时覆盖顽固错误列表中的记录。
  const stubbornErrors = profile.value?.stubborn_errors ?? []
  const recentErrors = profile.value?.recent_errors ?? []
  const recordsById = new Map<number, ProfileErrorRecord>()
  for (const item of stubbornErrors) recordsById.set(item.id, item)
  const recentOnly: ProfileErrorRecord[] = []
  for (const item of recentErrors) {
    if (!recordsById.has(item.id)) recentOnly.push(item)
    recordsById.set(item.id, item)
  }
  const timeline: ProfileErrorRecord[] = []
  let stubbornIndex = 0
  let recentIndex = 0
  while (stubbornIndex < stubbornErrors.length || recentIndex < recentOnly.length) {
    const stubbornError = stubbornErrors[stubbornIndex]
    const recentError = recentOnly[recentIndex]
    if (
      stubbornError &&
      (!recentError || stubbornError.created_at.localeCompare(recentError.created_at) >= 0)
    ) {
      timeline.push(recordsById.get(stubbornError.id) ?? stubbornError)
      stubbornIndex += 1
    } else if (recentError) {
      timeline.push(recentError)
      recentIndex += 1
    }
  }

  const typeCounts = new Map<string, number>()
  let reinforcingCount = 0
  for (const item of timeline) {
    if (!fixedIds.value.has(item.id)) reinforcingCount++
    typeCounts.set(item.error_type, (typeCounts.get(item.error_type) ?? 0) + 1)
  }

  return {
    totalAttempts,
    totalErrors,
    timeline,
    reinforcingCount,
    typeOptionData: [...typeCounts.entries()].map(([name, value]) => ({ name, value })),
  }
})
const totalAttempts = computed(() => profileSummary.value.totalAttempts)
const totalErrors = computed(() => profileSummary.value.totalErrors)
const timeline = computed(() => profileSummary.value.timeline)
const reinforcingCount = computed(() => profileSummary.value.reinforcingCount)

const TIMELINE_BATCH_SIZE = 50
const visibleTimelineCount = ref(TIMELINE_BATCH_SIZE)
const visibleTimeline = computed(() => timeline.value.slice(0, visibleTimelineCount.value))

function showMoreTimeline() {
  visibleTimelineCount.value += TIMELINE_BATCH_SIZE
}

// 问题类型分布：三色统一
const typeOptionData = computed(() => profileSummary.value.typeOptionData)

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

/** 掌握度高用绿色、中等用蓝色、较低用琥珀色。 */
function masteryTone(mastery: number): string {
  if (mastery >= 0.8) return 'tone-green'
  if (mastery >= 0.5) return 'tone-blue'
  return 'tone-amber'
}

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}
function fmtDate(t: string): string {
  return t.replace('T', ' ').slice(0, 10)
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
.profile-page-head { display: flex; align-items: center; justify-content: flex-end; gap: 16px; }
.profile-report-link { flex-shrink: 0; }
/* ================= 学习概览 ================= */
.profile-summary-card { margin-bottom: 16px; }
.profile-summary { padding: 22px 24px; border: 1px solid var(--border); border-radius: var(--radius-surface); background: var(--card); box-shadow: var(--shadow); }
.profile-identity { min-width: 0; }
.profile-name { color: var(--text); font-size: clamp(24px, 3vw, 32px); font-weight: 700; line-height: 1.2; }
.profile-meta { margin-top: 6px; color: var(--text-2); font-size: 14px; }
.profile-muted { color: var(--text-2); }
.profile-amber { color: var(--amber-strong); }
.profile-green { color: var(--green-strong); }
.profile-divider { height: 1px; margin: 18px 0 14px; border: 0; background: var(--border); }
.profile-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.profile-stat { min-width: 0; padding: 12px 14px; border: 1px solid var(--border); border-radius: var(--radius-control); background: var(--surface-2); }
.profile-stat-num { font-size: clamp(24px, 2.5vw, 32px); font-weight: 700; line-height: 1.15; }
.profile-stat-label { margin-top: 3px; color: var(--text-2); font-size: 13px; }
.profile-mastery { margin-top: 20px; }
.profile-section-title { margin-bottom: 10px; color: var(--text); font-size: 16px; font-weight: 650; }
.mastery-row { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.mastery-point { flex: 0 0 118px; overflow: hidden; color: var(--text); font-size: 14px; text-align: right; text-overflow: ellipsis; white-space: nowrap; }
.mastery-track { position: relative; flex: 1; height: 10px; overflow: hidden; border-radius: var(--radius-pill); background: var(--surface-2); }
.mastery-fill { display: block; height: 100%; border-radius: inherit; background: var(--primary); transition: width 0.35s ease; }
.mastery-fill.tone-green { background: var(--green); }
.mastery-fill.tone-amber { background: var(--amber); }
.mastery-percent { flex: 0 0 46px; color: var(--text-2); font-size: 13px; text-align: right; }
.profile-empty { margin-top: 16px; font-size: 14px; }
.profile-message { max-width: 640px; margin-top: 18px; padding: 12px 14px; border-left: 3px solid var(--primary); border-radius: 0 var(--radius-control) var(--radius-control) 0; background: var(--primary-50); }
.profile-message-label { margin-bottom: 3px; color: var(--primary-dark); font-size: 13px; font-weight: 650; }
.profile-message-text { color: var(--text); font-size: 14px; line-height: 1.7; }

@media (max-width: 720px) {
  .profile-summary { padding: 18px 16px; }
  .profile-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .mastery-row { gap: 9px; }
  .mastery-point { flex-basis: 92px; font-size: 13px; }
}
@media (prefers-reduced-motion: reduce) { .mastery-fill { transition: none; } }

/* ================= 成长记录表（课表式网格） ================= */
.record-wrap { overflow-x: auto; }
.record-table {
  width: 100%; min-width: 640px; border-collapse: collapse; font-size: 14px;
  border: 1px solid var(--border);
}
.record-table th, .record-table td {
  padding: 10px 12px; text-align: left; vertical-align: middle;
  border: 1px solid var(--border);
}
.record-table th {
  background: var(--primary-50); color: var(--primary-dark);
  font-size: 13px; font-weight: 700; white-space: nowrap;
  border-bottom: 1px solid var(--border-strong);
}
.record-table tbody tr:nth-child(even) td { background: var(--surface-2); }
.record-time { white-space: nowrap; color: var(--text-2); font-size: 13px; }
.record-step { font-weight: 600; }
</style>
