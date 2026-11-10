<!-- 学生端：我的档案。黑板呈现学习概览，记录区沿用全站表格与状态色。
     文案伦理：学生端用「需要加固的知识点」「已订正」「继续保持」，不出现贴标签术语；
     「已订正」口径 = 本机提交订正且判定正确；知识点「已修复」以学习报告为准。 -->
<template>
  <div class="page">
    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-if="profile">
      <section class="board-frame" aria-label="学习概览">
        <div class="board">
          <div class="board-identity">
            <div class="chalk-name chalk">{{ profile.student.name }}</div>
            <p class="chalk-meta chalk-dim">
              学号 <span class="chalk tnum">{{ profile.student.student_no || '—' }}</span>
              · 身份 学生
              <template v-if="profile.student.created_at">
                · {{ fmtDate(profile.student.created_at) }} 来到 Remedi
              </template>
            </p>
          </div>

          <div class="chalk-divider"></div>

          <div class="board-stats">
            <div class="board-stat">
              <div class="board-stat-num chalk tnum">{{ totalAttempts }}</div>
              <div class="board-stat-label chalk-dim">累计作答</div>
            </div>
            <div class="board-stat">
              <div class="board-stat-num chalk tnum">{{ totalErrors }}</div>
              <div class="board-stat-label chalk-dim">累计发现问题</div>
            </div>
            <div class="board-stat">
              <div class="board-stat-num chalk chalk-yellow tnum">{{ reinforcingCount }}</div>
              <div class="board-stat-label chalk-dim">加固中</div>
            </div>
            <div class="board-stat">
              <div class="board-stat-num chalk chalk-green tnum">{{ fixedIds.size }}</div>
              <div class="board-stat-label chalk-dim">已订正错题</div>
            </div>
          </div>

          <div class="board-mastery" v-if="profile.knowledge_points.length">
            <p class="board-section-title chalk">知识点掌握度</p>
            <div v-for="k in profile.knowledge_points" :key="k.knowledge_point" class="chalk-row">
              <span class="chalk-kp chalk">{{ k.knowledge_point }}</span>
              <span class="chalk-track">
                <span
                  class="chalk-fill"
                  :class="masteryTone(k.mastery)"
                  :style="{ width: `${Math.max(4, Math.round(k.mastery * 100))}%` }"
                ></span>
                <span class="chalk-ticks" aria-hidden="true"></span>
              </span>
              <span class="chalk-pct chalk tnum">{{ Math.round(k.mastery * 100) }}%</span>
            </div>
          </div>
          <p v-else class="chalk-dim board-empty">暂无作答记录。</p>

          <div class="board-message" v-if="profile.suggestion">
            <p class="board-message-label chalk chalk-pink">老师寄语</p>
            <p class="chalk board-message-text">{{ sanitizeStudentCopy(profile.suggestion) }}</p>
          </div>

          <div class="board-ledge" aria-hidden="true">
            <span class="chalk-stick"></span>
            <span class="chalk-stick short"></span>
            <span class="board-eraser"></span>
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

/** 黑板掌握度条：高为粉笔绿，中等为粉笔白，较低为粉笔粉。 */
function masteryTone(mastery: number): string {
  if (mastery >= 0.8) return 'tone-green'
  if (mastery >= 0.5) return 'tone-white'
  return 'tone-pink'
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
/* ================= 学习黑板 ================= */
.board-frame {
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.14), rgba(0, 0, 0, 0.12)),
    repeating-linear-gradient(93deg, #8A5A33 0 46px, #96683D 46px 52px, #7C4F2A 52px 104px);
  border-radius: var(--radius-surface);
  padding: 14px;
  box-shadow: var(--shadow-lg), inset 0 2px 3px rgba(255, 255, 255, 0.25), inset 0 -3px 6px rgba(0, 0, 0, 0.3);
  margin-bottom: 16px;
}
.board {
  position: relative;
  background:
    radial-gradient(120% 90% at 30% 0%, rgba(255, 255, 255, 0.07), transparent 55%),
    repeating-linear-gradient(115deg, rgba(255, 255, 255, 0.016) 0 26px, transparent 26px 52px),
    linear-gradient(160deg, #33584A 0%, #2E4B3F 55%, #29473B 100%);
  border-radius: var(--radius-control);
  padding: 26px 30px 20px;
  box-shadow: inset 0 0 42px rgba(0, 0, 0, 0.35), inset 0 2px 8px rgba(0, 0, 0, 0.3);
  overflow: hidden;
}
.chalk {
  font-family: 'KaiTi', 'STKaiti', 'Kaiti SC', 'Segoe Print', 'Bradley Hand', 'Comic Sans MS', cursive;
  color: #F7F3E8;
  text-shadow: 0 0 1px rgba(247, 243, 232, 0.55), 0 0 7px rgba(247, 243, 232, 0.14);
  letter-spacing: 0.5px;
}
.chalk-dim {
  font-family: 'KaiTi', 'STKaiti', 'Kaiti SC', 'Segoe Print', 'Bradley Hand', 'Comic Sans MS', cursive;
  color: rgba(240, 238, 226, 0.72);
  letter-spacing: 0.5px;
}
.chalk-yellow { color: #FFE58A; text-shadow: 0 0 1px rgba(255, 229, 138, 0.6), 0 0 8px rgba(255, 229, 138, 0.2); }
.chalk-green { color: #B5E7A0; text-shadow: 0 0 1px rgba(181, 231, 160, 0.6), 0 0 8px rgba(181, 231, 160, 0.2); }
.chalk-pink { color: #FFB7C5; text-shadow: 0 0 1px rgba(255, 183, 197, 0.6), 0 0 8px rgba(255, 183, 197, 0.2); }
.board-identity { margin-top: 0; }
.chalk-name { font-size: 38px; font-weight: 700; line-height: 1.15; }
.chalk-meta { margin-top: 6px; font-size: 15px; }
.chalk-divider { height: 0; margin: 18px 0 4px; border-top: 2px dashed rgba(247, 243, 232, 0.4); transform: rotate(-0.15deg); }
.board-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }
.board-stat { min-width: 0; text-align: left; }
.board-stat-num { font-size: clamp(26px, 2.5vw, 34px); font-weight: 700; line-height: 1.1; }
.board-stat-label { margin-top: 2px; font-size: 13.5px; }
.board-mastery { margin-top: 20px; }
.board-section-title { margin-bottom: 10px; font-size: 16.5px; font-weight: 700; }
.chalk-row { display: flex; align-items: center; gap: 12px; margin-bottom: 9px; }
.chalk-kp { flex: 0 0 118px; overflow: hidden; font-size: 15px; text-align: right; text-overflow: ellipsis; white-space: nowrap; }
.chalk-track {
  position: relative; flex: 1; height: 17px; overflow: hidden;
  border: 2px solid rgba(247, 243, 232, 0.5);
  border-radius: 255px 14px 225px 14px / 14px 225px 14px 255px;
}
.chalk-fill {
  position: absolute; inset: 1px auto 1px 1px; border-radius: inherit;
  background: repeating-linear-gradient(100deg, rgba(255, 255, 255, 0.16) 0 7px, transparent 7px 13px), rgba(247, 243, 232, 0.92);
  transition: width 0.5s ease;
}
.chalk-fill.tone-green { background: repeating-linear-gradient(100deg, rgba(255, 255, 255, 0.16) 0 7px, transparent 7px 13px), rgba(181, 231, 160, 0.92); }
.chalk-fill.tone-pink { background: repeating-linear-gradient(100deg, rgba(255, 255, 255, 0.16) 0 7px, transparent 7px 13px), rgba(255, 183, 197, 0.92); }
.chalk-ticks {
  position: absolute; inset: 0;
  background:
    linear-gradient(90deg, transparent calc(25% - 1px), rgba(20, 40, 32, 0.45) 25%, transparent calc(25% + 1px)),
    linear-gradient(90deg, transparent calc(50% - 1px), rgba(20, 40, 32, 0.45) 50%, transparent calc(50% + 1px)),
    linear-gradient(90deg, transparent calc(75% - 1px), rgba(20, 40, 32, 0.45) 75%, transparent calc(75% + 1px));
}
.chalk-pct { flex: 0 0 46px; font-size: 15px; }
.board-empty { margin-top: 16px; font-size: 15px; }
.board-message { max-width: 640px; margin-top: 18px; transform: rotate(-0.3deg); }
.board-message-label { margin-bottom: 3px; font-size: 14px; font-weight: 700; }
.board-message-text { font-size: 16.5px; line-height: 1.75; }
.board-ledge { display: flex; align-items: flex-end; gap: 8px; margin-top: 18px; }
.chalk-stick {
  width: 44px; height: 7px; border-radius: var(--radius-micro);
  background: linear-gradient(180deg, #FFFFFF, #E9E4D2);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35); transform: rotate(-2deg);
}
.chalk-stick.short { width: 26px; transform: rotate(1.5deg); background: linear-gradient(180deg, #FFE58A, #F3D97B); }
.board-eraser {
  width: 56px; height: 15px; margin-left: auto; border-radius: var(--radius-micro);
  background: linear-gradient(180deg, #B08954 0 55%, #4B4B4B 55% 100%);
  box-shadow: 0 2px 3px rgba(0, 0, 0, 0.4); transform: rotate(-1deg);
}

@media (max-width: 720px) {
  .board-frame { padding: 9px; }
  .board { padding: 20px 18px 16px; }
  .chalk-name { font-size: 31px; }
  .board-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .board-stat-num { font-size: 29px; }
  .chalk-row { gap: 9px; }
  .chalk-kp { flex-basis: 92px; font-size: 14px; }
}
@media (prefers-reduced-motion: reduce) { .chalk-fill { transition: none; } }

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
