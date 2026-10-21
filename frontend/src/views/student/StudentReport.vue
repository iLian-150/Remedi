<!-- 学生端：学习报告（v0.2.1 新增；v0.3.0 悬挂科目卡；v0.5.0 掉落动画；v0.6.0 拆独立详情页）
     对应开题报告「学习记忆层 + 教学反馈层」。本页是落地层：只保留悬挂科目卡 + 简要汇总；
     科目详情（总览 / 知识点 / 验证 / 错题时间线 / 步骤诊断）已拆到独立页
     /student/report/:subject（StudentReportSubject.vue），带「返回学习报告」按钮。
     点可用科目吊牌：先播掉落动画（挂绳断开、卡片加速下坠淡出，约 450ms），
     动画结束 router.push 跳详情页；占位卡不跳转，
     prefers-reduced-motion 时跳过动画直接跳转。
     文案伦理：不出现「顽固」「置信度」等术语（与既有页面一致）。 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>学习报告</h2>
      <p class="page-sub">按科目看看自己的进步轨迹：点开科目牌，进到详情里看哪个知识点还没修好、错过几次。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-if="!loading">
      <!-- 落地层：科目悬挂卡（吊牌）——数学真实数据可点进详情，其余科目占位 -->
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
            :class="{ placeholder: s.placeholder }"
            :disabled="s.placeholder"
            @click="enterSubject(s)"
          >
            <span class="hang-string"></span>
            <span class="hang-hole"></span>
            <span class="hang-name">{{ s.name }}</span>
            <template v-if="!s.placeholder">
              <span class="hang-stats">
                提交 <span class="tnum">{{ s.data?.submission_count ?? 0 }}</span> 次 ·
                待修复 <span class="tnum">{{ s.data?.pending_fix_count ?? 0 }}</span> 个知识点
              </span>
              <span class="hang-bar"><span :style="{ width: `${Math.round((s.data?.fixed_ratio ?? 0) * 100)}%` }"></span></span>
              <span class="hang-ratio">知识修复进度 <span class="tnum">{{ Math.round((s.data?.fixed_ratio ?? 0) * 100) }}%</span></span>
              <span class="hang-cta">点开看知识点明细</span>
            </template>
            <span v-else class="hang-soon">即将上线</span>
          </button>
        </div>
      </div>
      <p v-if="!report.length" class="hint" style="margin-bottom: 16px">
        还没有作答记录，先去 <router-link to="/student/chat" style="color: var(--primary)">智能批改</router-link> 拍一张作业照片，报告就会慢慢长出来。
      </p>

      <!-- 简要汇总（v0.6.0）：真实科目的关键数字一览，详情进科目页看 -->
      <div v-if="report.length" class="card summary-card">
        <h3><AppIcon name="chart" :size="18" /> 我的进步概览</h3>
        <div class="summary-grid">
          <div v-for="subj in report" :key="subj.subject" class="summary-item">
            <span class="summary-subject">{{ SUBJECT_TEXT[subj.subject] ?? subj.subject }}</span>
            <span class="summary-nums">
              累计提交 <b class="tnum">{{ subj.submission_count }}</b> 次 ·
              正确率 <b class="tnum">{{ Math.round(subj.correct_rate * 100) }}%</b> ·
              知识修复进度 <b class="tnum">{{ Math.round(subj.fixed_ratio * 100) }}%</b>
            </span>
          </div>
        </div>
        <p class="hint" style="margin-top: 10px">点上方任意一块科目牌，就能进详情看知识点明细、错题时间线，还能做验证题修复知识点。</p>
      </div>

      <div class="card summary-card">
        <h3><AppIcon name="sparkles" :size="18" /> 学习记忆</h3>
        <p class="hint">系统把错题、最近订正和变式验证连在一起；待教师审核的暂定判断不会记作已确认薄弱点。</p>
        <div v-if="learningMemory.length" class="memory-list">
          <div v-for="item in learningMemory" :key="`${item.subject}:${item.knowledge_point}`" class="memory-row">
            <span class="memory-tag">{{ SUBJECT_TEXT[item.subject] ?? item.subject }}</span>
            <div><b>{{ item.knowledge_point }}</b><p>{{ item.summary }}</p></div>
            <span class="memory-state" :class="`state-${item.state}`">{{ memoryStateLabel(item.state) }}</span>
          </div>
        </div>
        <div v-else class="empty">还没有足够的错题、订正和验证记录形成学习记忆。</div>
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
              <span class="summary-subject">{{ SUBJECT_TEXT[s.subject] ?? s.subject }}</span>
              <span class="hang-bar score-subject-bar"><span :style="{ width: `${Math.round(s.avg_rate * 100)}%` }"></span></span>
              <span class="summary-nums">平均得分率 <b class="tnum">{{ Math.round(s.avg_rate * 100) }}%</b> · {{ s.assignment_count }} 份作业</span>
            </div>
          </div>
          <div class="score-list">
            <p v-for="it in scoreData.items" :key="it.assignment_id" class="score-list-row">
              <span>{{ it.assignment_title }}</span>
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
import type { ReportScores, StudentLearningMemory, SubjectReport } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'
import { AsyncEChartLine as EChart } from '../../components/AsyncEChart'

const student = useStudentStore()
const router = useRouter()

const SUBJECT_TEXT: Record<string, string> = { math: '数学', english: '英语', physics: '物理', chemistry: '化学' }

const report = ref<SubjectReport[]>([])
const scoreData = ref<ReportScores | null>(null)
const learningMemory = ref<StudentLearningMemory[]>([])
const loading = ref(false)
const error = ref('')

function fmtScore(v: number): string {
  return String(Math.round(v * 10) / 10)
}

function memoryStateLabel(state: StudentLearningMemory['state']): string {
  return ({
    needs_practice: '需要订正', correcting: '订正中',
    reinforcing: '需要加固', mastered: '验证稳定'
  })[state]
}

/** 成绩走势折线：历次作业得分率（%），tooltip 带得分/满分 */
const scoreChartOption = computed(() => {
  const items = scoreData.value?.items ?? []
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: { dataIndex: number }[]) => {
        const it = items[params[0]?.dataIndex ?? 0]
        if (!it) return ''
        return `${it.assignment_title}<br/>得分 ${fmtScore(it.score)} / ${fmtScore(it.max_score)} 分 · 得分率 ${Math.round(it.rate * 100)}%`
      }
    },
    grid: { left: 8, right: 16, top: 28, bottom: 4, containLabel: true },
    xAxis: {
      type: 'category',
      data: items.map((it) => it.assignment_title),
      axisLabel: { interval: 0, rotate: items.length > 4 ? 28 : 0, fontSize: 11 }
    },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
    series: [
      {
        name: '得分率',
        type: 'line',
        smooth: true,
        symbolSize: 8,
        data: items.map((it) => Math.round(it.rate * 100)),
        lineStyle: { color: '#1D4ED8', width: 2.5 },
        itemStyle: { color: '#1D4ED8' },
        areaStyle: { color: 'rgba(29, 78, 216, 0.08)' },
        label: { show: true, formatter: '{c}%', fontSize: 11, color: '#475569' }
      }
    ]
  }
})

// ---------- 悬挂卡落地层 ----------
interface SubjectCard {
  key: string
  name: string
  placeholder: boolean
  data: SubjectReport | null
}

const subjectCards = computed<SubjectCard[]>(() => {
  const math = report.value.find((r) => r.subject === 'math') ?? null
  return [
    { key: 'math', name: '数学', placeholder: false, data: math },
    { key: 'english', name: '英语', placeholder: true, data: null },
    { key: 'physics', name: '物理', placeholder: true, data: null },
    { key: 'chemistry', name: '化学', placeholder: true, data: null }
  ]
})

// ---------- 掉落动画（v0.5.0，v0.6.0 改为跳页）：点科目吊牌 → 挂绳断开、卡片加速下坠
// 出视口 → router.push 到科目详情页；占位卡不触发；prefers-reduced-motion 时直接跳转。
const droppingKey = ref('')

async function enterSubject(s: SubjectCard) {
  if (s.placeholder || droppingKey.value) return
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

onMounted(async () => {
  loading.value = true
  const reportRequest = student.fetchReport()
  const scoresRequest = student.fetchReportScores()
  const memoryRequest = student.fetchLearningMemory()
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
  try {
    learningMemory.value = await memoryRequest
  } catch (e) {
    console.error(e)
  }
})
</script>

<style scoped>
/* ---------- 科目悬挂卡 ---------- */
.hang-row {
  display: flex; gap: 18px; flex-wrap: wrap;
  padding: 38px 4px 8px; margin-bottom: 14px;
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
  background: var(--card); border: 1px solid #E4E9F2; border-radius: 14px;
  box-shadow: var(--shadow);
  padding: 22px 16px 16px;
  cursor: pointer; font-family: var(--font); color: var(--text);
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}
.hang-wrap:hover .hang-card { transform: scale(1.045); box-shadow: 0 10px 22px rgba(15, 23, 42, 0.14); }
.hang-wrap:hover { animation-play-state: paused; }
.hang-card.placeholder {
  cursor: default; filter: grayscale(0.65); opacity: 0.68;
  background: #F4F6F9;
}
.hang-wrap:hover .hang-card.placeholder { transform: none; box-shadow: var(--shadow); }
.hang-string {
  position: absolute; top: -32px; left: 50%;
  width: 2px; height: 32px; margin-left: -1px;
  background: linear-gradient(#C7CEDA, #9AA7BC);
  border-radius: 1px;
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
.hang-bar {
  width: 100%; height: 8px; border-radius: 4px;
  background: #EDF0F4; overflow: hidden; display: block;
}
.hang-bar > span { display: block; height: 100%; background: var(--green); border-radius: 4px; }
.hang-ratio { font-size: 12.5px; color: var(--text-2); }
.hang-cta { font-size: 12.5px; color: var(--primary); font-weight: 600; margin-top: 2px; }
.hang-soon {
  font-size: 12.5px; font-weight: 600; color: var(--text-3);
  border: 1px dashed #C7CEDA; border-radius: 999px; padding: 3px 12px; margin-top: 8px;
}
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
.memory-row { display: flex; align-items: flex-start; gap: 12px; padding: 12px; border-radius: 11px; background: var(--bg); }
.memory-tag { min-width: 46px; color: var(--primary); font-size: 12px; font-weight: 700; }
.memory-row > div { flex: 1; min-width: 0; }
.memory-row b { font-size: 14px; }
.memory-row p { margin: 4px 0 0; color: var(--text-2); font-size: 13px; }
.memory-state { flex: none; font-size: 12px; color: var(--text-3); }
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
