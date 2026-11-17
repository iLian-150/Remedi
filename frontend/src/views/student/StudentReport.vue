<!-- 学生端：学习报告（v0.2.1 新增；v0.3.0 悬挂科目卡；v0.5.0 掉落动画；v0.6.0 拆独立详情页）
     对应开题报告「学习记忆层 + 教学反馈层」。本页是落地层：只保留悬挂科目卡 + 简要汇总；
     科目详情（总览 / 知识点 / 验证 / 错题时间线 / 步骤诊断）已拆到独立页
     /student/report/:subject（StudentReportSubject.vue），带「返回学习报告」按钮。
     点科目吊牌：先播掉落动画（挂绳断开、卡片加速下坠淡出，约 450ms），
     动画结束 router.push 跳详情页；
     prefers-reduced-motion 时跳过动画直接跳转。
     文案伦理：不出现「顽固」「置信度」等术语（与既有页面一致）。 -->
<template>
  <div class="page">
    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-if="!loading">
      <!-- 科目悬挂卡（吊牌）：数学、英语、物理、化学均可进入；有记录的其他学科一并展示 -->
      <div class="hang-row">
        <div
          v-for="(s, i) in subjectCards"
          :key="s.key"
          class="hang-wrap"
          :class="{ dropping: droppingKey === s.key }"
          :style="{ animationDuration: `${4.6 + i * 0.45}s`, animationDelay: `${-i * 1.25}s` }"
        >
          <button
            type="button"
            class="hang-card"
            @click="enterSubject(s)"
          >
            <span class="hang-string"></span>
            <span class="hang-hole"></span>
            <span class="hang-name">{{ s.name }}</span>
            <template v-if="s.data">
              <span class="hang-stats">
                提交 <span class="tnum">{{ s.data.submission_count }}</span> 次 ·
                待修复 <span class="tnum">{{ s.data.pending_fix_count }}</span> 个知识点
              </span>
              <span class="hang-bar"><span :style="{ width: `${Math.round(s.data.fixed_ratio * 100)}%` }"></span></span>
              <span class="hang-ratio">知识修复进度 <span class="tnum">{{ Math.round(s.data.fixed_ratio * 100) }}%</span></span>
              <span class="hang-cta">点开看知识点明细</span>
            </template>
            <template v-else>
              <span class="hang-empty">暂无记录</span>
              <span class="hang-cta">查看学科报告</span>
            </template>
          </button>
        </div>
      </div>
      <p v-if="!report.length" class="hint" style="margin-bottom: 16px">
        暂无学习记录，<router-link to="/student/assignments" style="color: var(--primary)">去做作业</router-link>。
      </p>

      <!-- 简要汇总（v0.6.0）：真实科目的关键数字一览，详情进科目页看 -->
      <div v-if="report.length" class="card summary-card">
        <h3><AppIcon name="chart" :size="18" /> 我的进步概览</h3>
        <div class="summary-grid">
          <div v-for="subj in report" :key="subj.subject" class="summary-item">
            <span class="summary-subject">{{ subjectLabel(subj.subject) }}</span>
            <span class="summary-nums">
              题目 <b class="tnum">{{ subj.question_count }}</b> 道 ·
              累计提交 <b class="tnum">{{ subj.submission_count }}</b> 次 ·
              正确率 <b class="tnum">{{ Math.round(subj.correct_rate * 100) }}%</b> ·
              知识修复进度 <b class="tnum">{{ Math.round(subj.fixed_ratio * 100) }}%</b>
            </span>
          </div>
        </div>
      </div>

      <div class="card summary-card">
        <h3><AppIcon name="sparkles" :size="18" /> 学习记忆</h3>
        <div v-if="memoryLoadError" class="memory-load-error" role="status">
          {{ memoryLoadError }}
          <button type="button" class="btn small secondary" :disabled="memoryLoading" @click="loadMemoryData">
            {{ memoryLoading ? '加载中…' : '重试' }}
          </button>
        </div>
        <div v-if="learningMemory.length || assistantPreferences.length" class="memory-list">
          <div v-if="assistantPreferences.length" class="memory-row">
            <span class="memory-tag">回答偏好</span>
            <div><p>{{ assistantPreferences.map((item) => item.label).join('；') }}</p></div>
            <span class="memory-state">跨对话适用</span>
          </div>
          <div v-for="item in learningMemory" :key="`${item.subject}:${item.knowledge_point}`" class="memory-row">
            <span class="memory-tag">{{ subjectLabel(item.subject) }}</span>
            <div><b>{{ item.knowledge_point }}</b><p>{{ item.summary }}</p></div>
            <span class="memory-state" :class="`state-${item.state}`">{{ memoryStateLabel(item.state) }}</span>
          </div>
        </div>
        <div v-else-if="memoryLoading" class="empty">正在读取学习记忆…</div>
        <div v-else-if="!memoryLoadError" class="empty">还没有足够的错题、订正和验证记录形成学习记忆。</div>
      </div>

      <!-- 成绩分析（评分系统）：只统计老师审核通过并出分的作业 -->
      <div class="card summary-card">
        <h3><AppIcon name="chart" :size="18" /> 成绩分析</h3>
        <template v-if="scoreData && scoreData.items.length">
          <p class="score-overall">
            总体平均得分率 <b class="tnum">{{ scoreData.overall_avg_rate !== null ? Math.round(scoreData.overall_avg_rate * 100) + '%' : '—' }}</b>
            <span class="hint">（共 {{ scoreData.items.length }} 份已出分作业）</span>
          </p>
          <EChart :option="scoreChartOption" style="height: 280px" />
          <div class="summary-grid" style="margin-top: 12px">
            <div v-for="s in scoreData.subjects" :key="s.subject" class="summary-item">
              <span class="summary-subject">{{ subjectLabel(s.subject) }}</span>
              <span class="hang-bar score-subject-bar"><span :style="{ width: `${Math.round(s.avg_rate * 100)}%` }"></span></span>
              <span class="summary-nums">平均得分率 <b class="tnum">{{ Math.round(s.avg_rate * 100) }}%</b> · {{ s.assignment_count }} 份作业</span>
            </div>
          </div>
          <div class="score-list">
            <p v-for="it in scoreData.items" :key="it.assignment_id" class="score-list-row">
              <span>
                {{ it.assignment_title }}
                <small v-if="it.subjects.length > 1" class="hint">· {{ formatSubjects(it.subjects) }}</small>
              </span>
              <span class="tnum">{{ fmtScore(it.score) }} / {{ fmtScore(it.max_score) }} 分 · 得分率 {{ Math.round(it.rate * 100) }}%</span>
            </p>
          </div>
        </template>
        <div v-else class="empty">还没有已出分的作业。完成作业批改后，这里就会出现你的成绩走势。</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useStudentStore } from '../../stores/student'
import type {
  AssignmentSubjectScore,
  ReportScores,
  StudentAssistantPreferenceItem,
  StudentLearningMemory,
  SubjectReport
} from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'
import { AsyncEChartLine as EChart } from '../../components/AsyncEChart'
import { getSubjectLabel } from '../../utils/subjectLabels'

const student = useStudentStore()
const router = useRouter()

const subjectLabel = (subject: string) => subject === 'mixed' ? '综合' : getSubjectLabel(subject)

const report = ref<SubjectReport[]>([])
const scoreData = ref<ReportScores | null>(null)
const learningMemory = ref<StudentLearningMemory[]>([])
const assistantPreferences = ref<StudentAssistantPreferenceItem[]>([])
const memoryLoading = ref(false)
const memoryLoadError = ref('')
const loading = ref(false)
const error = ref('')

function fmtScore(v: number): string {
  return String(Math.round(v * 10) / 10)
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char] ?? char)
}

function formatSubjects(subjects: string[]): string {
  return subjects.map(subjectLabel).join('、')
}

function memoryStateLabel(state: StudentLearningMemory['state']): string {
  return ({
    needs_practice: '需要订正', correcting: '订正中',
    reinforcing: '需要加固', mastered: '验证稳定'
  })[state]
}

interface ScoreChartAssignment {
  title: string
  score: number
  max_score: number
}

interface ScoreChartPoint {
  value: number
  score: number
  max_score: number
  assignments: ScoreChartAssignment[]
}

const scoreColorTokens = [
  ['--primary', '#315DDB'],
  ['--amber', '#D97706'],
  ['--purple', '#7C3AED'],
  ['--green', '#059669']
] as const

function themeColor(token: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(token).trim() || fallback
}

function shortDateLabel(date: string): string {
  const [, month, day] = date.split('-')
  return month && day ? `${Number(month)}/${Number(day)}` : date
}

function longDateLabel(date: string): string {
  const [year, month, day] = date.split('-')
  return year && month && day ? `${year}年${Number(month)}月${Number(day)}日` : date
}

function subjectScoresForItem(item: ReportScores['items'][number]): AssignmentSubjectScore[] {
  if (item.subject_scores?.length) return item.subject_scores
  return [{
    subject: item.subject || 'mixed',
    date: item.date,
    score: item.score,
    max_score: item.max_score,
    rate: item.rate
  }]
}

/** 每科一条折线；同一天同科多份作业按总得分/总满分合并。 */
const scoreChartOption = computed(() => {
  const items = scoreData.value?.items ?? []
  const buckets = new Map<string, ScoreChartPoint>()
  const subjectSet = new Set<string>()
  const dateSet = new Set<string>()

  for (const item of items) {
    for (const subjectScore of subjectScoresForItem(item)) {
      const date = subjectScore.date?.slice(0, 10)
      if (!date || subjectScore.max_score <= 0) continue
      const subject = subjectScore.subject || 'mixed'
      const key = `${date}\u0000${subject}`
      let point = buckets.get(key)
      if (!point) {
        point = { value: 0, score: 0, max_score: 0, assignments: [] }
        buckets.set(key, point)
      }
      point.score += subjectScore.score
      point.max_score += subjectScore.max_score
      point.assignments.push({
        title: item.assignment_title,
        score: subjectScore.score,
        max_score: subjectScore.max_score
      })
      subjectSet.add(subject)
      dateSet.add(date)
    }
  }

  for (const point of buckets.values()) {
    point.value = Math.round(point.score / point.max_score * 100)
  }

  const subjects = [...subjectSet].sort((a, b) => subjectLabel(a).localeCompare(subjectLabel(b), 'zh-CN'))
  const dates = [...dateSet].sort()
  const palette = subjects.map((_, index) => {
    const [token, fallback] = scoreColorTokens[index % scoreColorTokens.length]
    return themeColor(token, fallback)
  })

  return {
    color: palette,
    legend: {
      show: subjects.length > 1,
      top: 0,
      type: 'scroll',
      textStyle: { color: themeColor('--text-2', '#66758D'), fontSize: 12 }
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line' },
      formatter: (params: Array<{
        axisValue?: string | number
        seriesName?: string
        data?: ScoreChartPoint | null
      }>) => {
        const date = String(params[0]?.axisValue ?? '')
        const points = params.filter((param) => param.data && param.data.max_score > 0)
        if (!date || !points.length) return ''
        const details = points.map((param) => {
          const point = param.data!
          const assignmentDetails = point.assignments
            .map((assignment) => `${escapeHtml(assignment.title)} ${fmtScore(assignment.score)}/${fmtScore(assignment.max_score)}分`)
            .join('、')
          return `<div style="margin-top: 5px"><b>${escapeHtml(param.seriesName ?? '')} ${point.value}%</b> · ${fmtScore(point.score)} / ${fmtScore(point.max_score)} 分<br/><span>${assignmentDetails}</span></div>`
        }).join('')
        return `<strong>${escapeHtml(longDateLabel(date))}</strong>${details}`
      }
    },
    grid: { left: 8, right: 16, top: subjects.length > 1 ? 38 : 16, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: dates,
      axisLabel: {
        interval: 'auto',
        hideOverlap: true,
        rotate: dates.length > 8 ? 30 : 0,
        formatter: (value: string) => shortDateLabel(value),
        fontSize: 11,
        color: themeColor('--text-3', '#8F9BB0')
      },
      axisLine: { lineStyle: { color: themeColor('--border-strong', '#CBD5E4') } }
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      splitNumber: 4,
      axisLabel: { formatter: '{value}%', color: themeColor('--text-3', '#8F9BB0') },
      splitLine: { lineStyle: { color: themeColor('--border', '#E3E9F2') } }
    },
    series: subjects.map((subject, index) => ({
        name: subjectLabel(subject),
        type: 'line',
        smooth: true,
        connectNulls: false,
        symbol: 'circle',
        symbolSize: 7,
        data: dates.map((date) => buckets.get(`${date}\u0000${subject}`) ?? null),
        lineStyle: { color: palette[index], width: 2.5 },
        itemStyle: { color: palette[index] },
        emphasis: { focus: 'series' }
      }))
  }
})

// ---------- 悬挂卡落地层 ----------
interface SubjectCard {
  key: string
  name: string
  data: SubjectReport | null
}

const subjectCards = computed<SubjectCard[]>(() => {
  const launchSubjects = ['math', 'english', 'physics', 'chemistry']
  const primary = launchSubjects.map((key) => ({
    key,
    name: getSubjectLabel(key),
    data: report.value.find((item) => item.subject === key) ?? null
  }))
  const additional = report.value
    .filter((item) => !launchSubjects.includes(item.subject))
    .map((item) => ({ key: item.subject, name: subjectLabel(item.subject), data: item }))
  return [...primary, ...additional]
})

// ---------- 掉落动画（v0.5.0，v0.6.0 改为跳页）：点科目吊牌 → 挂绳断开、卡片加速下坠
// 出视口 → router.push 到科目详情页；prefers-reduced-motion 时直接跳转。
const droppingKey = ref('')

async function enterSubject(s: SubjectCard) {
  if (droppingKey.value) return
  const reduceMotion =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (!reduceMotion) {
    droppingKey.value = s.key
    await new Promise((r) => setTimeout(r, 460))
    droppingKey.value = ''
  }
  router.push(`/student/report/${s.key}`)
}

async function loadMemoryData() {
  memoryLoading.value = true
  memoryLoadError.value = ''
  const [memoryResult, preferenceResult] = await Promise.allSettled([
    student.fetchLearningMemory(),
    student.fetchAssistantPreferences()
  ])
  const failedLoads: string[] = []
  if (memoryResult.status === 'fulfilled') {
    learningMemory.value = memoryResult.value
  } else {
    failedLoads.push('学科记忆')
    console.error(memoryResult.reason)
  }
  if (preferenceResult.status === 'fulfilled') {
    assistantPreferences.value = preferenceResult.value.items
  } else {
    failedLoads.push('回答偏好')
    console.error(preferenceResult.reason)
  }
  if (failedLoads.length) {
    memoryLoadError.value = `${failedLoads.join('、')}读取失败，请重试。`
  }
  memoryLoading.value = false
}

onMounted(async () => {
  loading.value = true
  const reportRequest = student.fetchReport()
  const scoresRequest = student.fetchReportScores()
  const memoryRequest = loadMemoryData()
  try {
    report.value = await reportRequest
  } catch (e) {
    error.value = '学习报告加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
  // 成绩分析独立加载：失败不影响报告主体
  try {
    scoreData.value = await scoresRequest
  } catch (e) {
    console.error(e)
  }
  await memoryRequest
})
</script>

<style scoped>
/* ---------- 科目悬挂卡 ---------- */
.hang-row {
  --hang-string-height: 32px;
  display: flex; gap: 18px; flex-wrap: wrap;
  padding: var(--hang-string-height) 0 8px; margin-bottom: 14px;
}
.hang-wrap {
  transform-origin: top center;
  animation: hang-sway 5s ease-in-out infinite;
}
@keyframes hang-sway {
  0%, 100% { transform: rotate(-1.5deg); }
  50% { transform: rotate(1.5deg); }
}
.hang-card {
  position: relative;
  width: 196px; min-height: 168px;
  display: flex; flex-direction: column; align-items: center; gap: 7px;
  background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-surface);
  box-shadow: var(--shadow);
  padding: 22px 16px 16px;
  cursor: pointer; font-family: var(--font); color: var(--text);
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}
.hang-wrap:hover .hang-card { transform: scale(1.045); box-shadow: var(--shadow-md); }
.hang-wrap:hover { animation-play-state: paused; }
.hang-string {
  position: absolute; bottom: 100%; left: 50%;
  width: 2px; height: var(--hang-string-height); margin-left: -1px;
  background: linear-gradient(#C7CEDA, #9AA7BC);
  border-radius: var(--radius-micro);
}
.hang-hole {
  position: absolute; top: 9px; left: 50%;
  width: 12px; height: 12px; margin-left: -6px;
  border-radius: 50%;
  border: 2px solid #9AA7BC; background: var(--bg);
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.25);
}
.hang-name { font-size: 19px; font-weight: 800; margin-top: 6px; }
.hang-stats { font-size: 12.5px; color: var(--text-2); text-align: center; line-height: 1.5; }
.hang-empty { font-size: 12.5px; color: var(--text-2); }
.hang-bar {
  width: 100%; height: 8px; border-radius: var(--radius-pill);
  background: #EDF0F4; overflow: hidden; display: block;
}
.hang-bar > span { display: block; height: 100%; background: var(--green); border-radius: var(--radius-pill); }
.hang-ratio { font-size: 12.5px; color: var(--text-2); }
.hang-cta { font-size: 12.5px; color: var(--primary); font-weight: 600; margin-top: 2px; }
/* ---------- 掉落动画 ---------- */
/* 挂绳先"断"（快速消失），卡片以加速曲线（近似重力）下坠、轻微旋转并淡出，随后跳页 */
.hang-wrap.dropping {
  position: relative; z-index: 6; pointer-events: none;
  animation: card-fall 0.45s cubic-bezier(0.55, 0.06, 0.68, 0.19) forwards;
}
@keyframes card-fall {
  0% { transform: rotate(0deg) translateY(0); opacity: 1; }
  15% { transform: rotate(1.4deg) translateY(8px); opacity: 1; }
  100% { transform: rotate(7deg) translateY(105vh); opacity: 0.1; }
}
.hang-wrap.dropping .hang-string {
  opacity: 0; transform: scaleY(0.25); transform-origin: top center;
  transition: opacity 0.09s ease, transform 0.09s ease;
}
.hang-wrap.dropping .hang-hole { opacity: 0.35; }
@media (prefers-reduced-motion: reduce) {
  .hang-wrap { animation: none; }
  .hang-card { transition: none; }
  .hang-wrap.dropping { animation: none; }
}

/* ---------- 简要汇总 ---------- */
.summary-grid { display: flex; flex-direction: column; gap: 10px; }
.summary-item { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.summary-subject { font-size: 15px; font-weight: 700; min-width: 44px; }
.summary-nums { font-size: 13.5px; color: var(--text-2); }
.summary-nums b { color: var(--text); }
.memory-list { display: flex; flex-direction: column; gap: 10px; margin-top: 14px; }
.memory-row { display: flex; align-items: flex-start; gap: 12px; padding: 12px; border-radius: var(--radius-control); background: var(--bg); }
.memory-tag { min-width: 46px; color: var(--primary); font-size: 12px; font-weight: 700; }
.memory-row > div { flex: 1; min-width: 0; }
.memory-row b { font-size: 14px; }
.memory-row p { margin: 4px 0 0; color: var(--text-2); font-size: 13px; }
.memory-state { flex: none; font-size: 12px; color: var(--text-3); }
.memory-load-error { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--red); font-size: 13px; }
.state-mastered { color: var(--green); }
.state-needs_practice, .state-reinforcing { color: var(--amber); }

/* ---------- 成绩分析 ---------- */
.score-overall { font-size: 14.5px; margin-bottom: 6px; }
.score-overall b { color: var(--primary); font-size: 18px; }
.score-subject-bar { width: 150px; flex: none; align-self: center; }
.score-subject-bar > span { background: var(--primary); }
.score-list { margin-top: 14px; border-top: 1px solid #F1F3F6; }
.score-list-row {
  display: flex; align-items: baseline; justify-content: space-between; gap: 12px;
  padding: 7px 0; border-bottom: 1px solid #F7F8FA; font-size: 13.5px;
}
.score-list-row:last-child { border-bottom: none; }
.score-list-row .tnum { color: var(--text-2); white-space: nowrap; }
</style>
