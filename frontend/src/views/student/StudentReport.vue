<!-- 学生端：学习报告（v0.2.1 新增；v0.4.0 双列详情 + 二次验证；v0.5.0 科目卡掉落动画）
     对应开题报告「学习记忆层 + 教学反馈层」，四级下钻：
       科目 → 知识点（状态/错误率） → 错题时间线（纵向） → 步骤诊断（跳现有诊断报告页定位到该次提交）
     v0.5.0：点可用科目吊牌先播掉落动画（挂绳断开、卡片加速下坠淡出，约 450ms），
       动画结束再展开详情，详情内容从上方落下带一次小回弹；占位卡不触发，
       prefers-reduced-motion 时直接展开不播动画。
     v0.4.0：科目详情改双列（左知识点列表、右错题时间线）；知识点四态
       （待修复 / 反复出错 / 已订正待验证 / 已修复），未修复的提供「去验证」，
       在右列内嵌 VerifyPanel 做变式题，通过后刷新状态与修复进度。
     数据源：GET /api/student/report、GET /api/student/report/knowledge-points/{name}/errors、
             POST /api/student/verifications（验证，见 VerifyPanel）
     文案伦理：学生端用「待修复 / 反复出错 / 已订正待验证 / 已修复」，不出现「顽固」「置信度」。 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>学习报告</h2>
      <p class="page-sub">按科目看看自己的进步轨迹：哪个知识点还没修好、错过几次、最近一次错在哪一步。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-if="!loading">
      <!-- 落地层（v0.3.0）：科目悬挂卡（吊牌）——数学真实数据可点进下钻，其余科目占位 -->
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
            :class="{ placeholder: s.placeholder, active: activeSubject === s.key }"
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

      <div v-if="activeSubject" ref="detailRef" :class="{ 'land-in': landDetail }">
      <section v-for="subj in detailSubjects" :key="subj.subject">
        <!-- 一级：科目总览 -->
        <div class="card">
          <h3><AppIcon name="book" :size="18" /> {{ SUBJECT_TEXT[subj.subject] ?? subj.subject }}</h3>
          <div class="stat-row">
            <div class="stat">
              <div class="stat-num tnum">{{ subj.submission_count }}</div>
              <div class="stat-label">累计提交</div>
            </div>
            <div class="stat green">
              <div class="stat-num tnum">{{ Math.round(subj.correct_rate * 100) }}%</div>
              <div class="stat-label">正确率</div>
            </div>
            <div class="stat amber">
              <div class="stat-num tnum">{{ subj.pending_fix_count }}</div>
              <div class="stat-label">待修复知识点</div>
            </div>
          </div>
          <div class="fix-progress">
            <div class="fix-progress-head">
              <span>知识修复进度</span>
              <span class="tnum">{{ Math.round(subj.fixed_ratio * 100) }}%</span>
            </div>
            <div class="fix-bar"><div :style="{ width: `${Math.round(subj.fixed_ratio * 100)}%` }"></div></div>
            <p class="hint">订正好错题、再做对一道同类题通过验证，才算真正修复——这里是已修复知识点占出过错知识点的比例。</p>
          </div>
        </div>

        <!-- 二级 + 三级（v0.4.0 双列）：左 知识点列表 | 右 验证面板 + 错题时间线 -->
        <div class="report-grid">
          <div class="card">
            <h3><AppIcon name="target" :size="18" /> 知识点明细</h3>
            <p class="card-sub">按错误率从高到低排。点知识点在右列看错题时间线；还没修复的可以点「去验证」做一道同类题。</p>
            <div v-if="!subj.knowledge_points.length" class="empty">这个科目暂时没有错题记录，继续保持。</div>
            <div v-for="kp in subj.knowledge_points" :key="kp.name" class="kp-block">
              <div class="kp-row" :class="{ selected: selectedKey === kpKey(subj.subject, kp.name) }">
                <button type="button" class="kp-main-btn" @click="selectKp(subj.subject, kp)">
                  <span class="kp-main">
                    <span class="kp-name">{{ kp.name }}</span>
                    <span class="kp-meta">
                      出错 <span class="tnum">{{ kp.error_count }}</span> 次 · 提交 <span class="tnum">{{ kp.attempts }}</span> 次
                      <template v-if="kp.last_error_at"> · 最近出错 {{ fmtDate(kp.last_error_at) }}</template>
                    </span>
                    <span class="kp-bar"><span :style="{ width: `${Math.round(kp.error_rate * 100)}%` }"></span></span>
                  </span>
                  <span :class="`badge ${STATUS_BADGE[kp.status]}`">{{ STATUS_TEXT[kp.status] }}</span>
                  <span class="kp-rate tnum">{{ Math.round(kp.error_rate * 100) }}%</span>
                </button>
                <button
                  v-if="kp.status !== 'fixed'"
                  type="button"
                  class="btn small verify-btn"
                  @click="openVerify(subj.subject, kp)"
                >
                  去验证
                </button>
                <span v-else class="verify-done"><AppIcon name="check" :size="14" /> 已通过验证</span>
              </div>
            </div>
          </div>

          <div class="report-side">
            <VerifyPanel
              v-if="verifyKpName"
              :key="verifyKpName"
              :knowledge-point="verifyKpName"
              @passed="onVerifyPassed"
              @close="verifyKpName = ''"
            />

            <div class="card timeline-card">
              <h3>
                <AppIcon name="file" :size="18" /> 错题时间线
                <span v-if="selectedKp" class="badge badge-blue">{{ selectedKp.name }}</span>
              </h3>
              <p v-if="selectedKp" class="card-sub">
                当前状态：{{ STATUS_TEXT[selectedKp.status] }} · 出错 <span class="tnum">{{ selectedKp.error_count }}</span> 次
                <template v-if="selectedKp.status === 'awaiting_verify'">—— 错题都订正好了，点左边的「去验证」做对一道同类题，这个知识点就修复啦。</template>
              </p>
              <div v-if="!selectedKp" class="empty" style="padding: 22px 0">点左边任意一个知识点，这里会展开它下面的错题时间线。</div>
              <div v-else-if="timelineLoading" class="loading" style="padding: 16px 0">加载错题时间线…</div>
              <div v-else-if="!timeline.length" class="empty" style="padding: 16px 0">这个知识点下还没有错题记录。</div>
              <div v-else class="timeline">
                <div v-for="(item, i) in timeline" :key="i" class="timeline-item">
                  <span :class="item.corrected ? 'timeline-dot green' : errorTypeDotClass(item.error_type)"></span>
                  <div class="timeline-time">{{ fmtDateTime(item.created_at) }}</div>
                  <div class="timeline-body">
                    <p>
                      <strong>{{ item.assignment_title }}</strong> · {{ item.question_prompt }}
                    </p>
                    <p style="margin-top: 4px">
                      <ErrorTypeBadge :type="item.error_type as ErrorType" />
                      <span v-if="item.first_error_seq !== null" class="badge badge-gray">第 {{ item.first_error_seq }} 步出错</span>
                      <span v-if="item.corrected" class="badge badge-green">已订正</span>
                      <span v-else class="badge badge-gray">未订正</span>
                    </p>
                    <div class="toolbar" style="margin: 8px 0 0">
                      <button class="btn small secondary" @click="gotoDiagnosis(item.submission_id)">查看步骤诊断</button>
                      <router-link v-if="!item.corrected" to="/student/corrections">
                        <button class="btn small">去订正</button>
                      </router-link>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStudentStore } from '../../stores/student'
import type {
  ErrorType,
  KnowledgePointErrorItem,
  KnowledgePointStatus,
  ReportKnowledgePoint,
  SubjectReport
} from '../../api/types'
import { errorTypeDotClass } from '../../utils/errorType'
import AppIcon from '../../components/icons/AppIcon.vue'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import VerifyPanel from '../../components/VerifyPanel.vue'

const student = useStudentStore()
const router = useRouter()
const route = useRoute()

const SUBJECT_TEXT: Record<string, string> = { math: '数学', english: '英语', physics: '物理', chemistry: '化学' }
// v0.4.0 四态文案：fixed 专指「订正 + 通过二次验证」，与后端新口径一致
const STATUS_TEXT: Record<KnowledgePointStatus, string> = {
  pending: '待修复',
  stubborn: '反复出错',
  awaiting_verify: '已订正待验证',
  fixed: '已修复'
}
const STATUS_BADGE: Record<KnowledgePointStatus, string> = {
  pending: 'badge-amber',
  stubborn: 'badge-red',
  awaiting_verify: 'badge-blue',
  fixed: 'badge-green'
}

const report = ref<SubjectReport[]>([])
const loading = ref(false)
const error = ref('')

// ---------- 悬挂卡落地层（v0.3.0） ----------
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

const activeSubject = ref<string | null>(null)
const detailRef = ref<HTMLElement | null>(null)
const detailSubjects = computed(() =>
  report.value.filter((r) => r.subject === activeSubject.value)
)

// ---------- 掉落动画（v0.5.0）：点科目吊牌 → 挂绳断开、卡片加速下坠出视口 → 跳进详情，
// 详情内容从上方落下带一次小回弹。占位卡不触发；prefers-reduced-motion 时直接展开不播动画。
const droppingKey = ref('')
const landDetail = ref(false)

async function showDetail(s: SubjectCard) {
  activeSubject.value = s.key
  await nextTick()
  detailRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function enterSubject(s: SubjectCard) {
  if (s.placeholder || droppingKey.value) return
  const reduceMotion =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (reduceMotion) {
    await showDetail(s)
    return
  }
  droppingKey.value = s.key
  await new Promise((r) => setTimeout(r, 460))
  droppingKey.value = ''
  landDetail.value = true
  await showDetail(s)
  setTimeout(() => (landDetail.value = false), 650)
}

// ---------- 知识点选中（v0.4.0：时间线移到右列，选中态驱动右列面板） ----------
const selectedKey = ref('')
const selectedSubject = ref('')
const selectedKpName = ref('')
const timeline = ref<KnowledgePointErrorItem[]>([])
const timelineLoading = ref(false)

/** 从最新报告数据里取选中的知识点（刷新报告后状态自动跟随） */
const selectedKp = computed<ReportKnowledgePoint | null>(() => {
  const subj = report.value.find((r) => r.subject === selectedSubject.value)
  return subj?.knowledge_points.find((k) => k.name === selectedKpName.value) ?? null
})

function kpKey(subject: string, name: string): string {
  return `${subject}::${name}`
}

function fmtDate(t: string): string {
  return t.replace('T', ' ').slice(0, 10)
}
function fmtDateTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

async function loadTimeline() {
  if (!selectedKpName.value) return
  timeline.value = []
  timelineLoading.value = true
  try {
    timeline.value = await student.fetchKnowledgePointErrors(selectedKpName.value)
  } catch (e) {
    error.value = '错题时间线加载失败。'
    console.error(e)
  } finally {
    timelineLoading.value = false
  }
}

async function selectKp(subject: string, kp: ReportKnowledgePoint) {
  selectedKey.value = kpKey(subject, kp.name)
  selectedSubject.value = subject
  selectedKpName.value = kp.name
  await loadTimeline()
}

// ---------- 二次验证（v0.4.0） ----------
const verifyKpName = ref('')

async function openVerify(subject: string, kp: ReportKnowledgePoint) {
  await selectKp(subject, kp)
  verifyKpName.value = kp.name
}

async function onVerifyPassed() {
  // 通过验证 → 刷新报告（知识点状态变已修复、修复进度更新）与时间线
  try {
    report.value = await student.fetchReport()
  } catch (e) {
    console.error(e)
  }
  await loadTimeline()
}

function gotoDiagnosis(submissionId: number) {
  router.push({ path: '/student/feedback', query: { submission_id: submissionId } })
}

async function loadReport() {
  report.value = await student.fetchReport()
}

onMounted(async () => {
  loading.value = true
  try {
    await loadReport()
    // 深链：订正页「去验证」带 ?verify=<知识点名> 跳入时，直接展开该科目并打开验证面板
    const want = typeof route.query.verify === 'string' ? route.query.verify : ''
    if (want) {
      for (const subj of report.value) {
        const kp = subj.knowledge_points.find((k) => k.name === want)
        if (kp) {
          activeSubject.value = subj.subject
          await nextTick()
          detailRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
          await openVerify(subj.subject, kp)
          break
        }
      }
    }
  } catch (e) {
    error.value = '学习报告加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
/* ---------- 科目悬挂卡（v0.3.0） ---------- */
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
.hang-card.active { border-color: var(--primary); }
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
/* ---------- 掉落动画（v0.5.0） ---------- */
/* 挂绳先"断"（快速消失），卡片以加速曲线（近似重力）下坠、轻微旋转并淡出 */
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
/* 详情入场：从上方落下，落定带一次小回弹 */
.land-in { animation: land-drop 0.6s cubic-bezier(0.22, 1.15, 0.36, 1) both; }
@keyframes land-drop {
  0% { transform: translateY(-36px); opacity: 0; }
  55% { transform: translateY(6px); opacity: 1; }
  78% { transform: translateY(-2px); }
  100% { transform: translateY(0); opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .hang-wrap { animation: none; }
  .hang-card { transition: none; }
  .hang-wrap.dropping { animation: none; }
  .land-in { animation: none; }
}

.fix-progress { margin-top: 16px; }
.fix-progress-head { display: flex; justify-content: space-between; font-size: 13.5px; font-weight: 600; margin-bottom: 6px; }
.fix-bar { height: 10px; background: #EDF0F4; border-radius: 5px; overflow: hidden; }
.fix-bar > div { height: 100%; background: var(--green); border-radius: 5px; transition: width 0.3s; }
.fix-progress .hint { margin-top: 6px; }

/* ---------- v0.4.0 双列详情：左知识点 / 右时间线 ---------- */
.report-grid {
  display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 16px; align-items: start;
}
.report-grid > .card { margin-bottom: 0; }
.report-side { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.report-side > .card { margin-bottom: 0; }
@media (max-width: 1080px) {
  .report-grid { grid-template-columns: 1fr; }
}

.kp-block { border-bottom: 1px solid #F1F3F6; }
.kp-block:last-child { border-bottom: none; }
.kp-row {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 4px; border-radius: 10px;
}
.kp-row.selected { background: var(--primary-50); }
.kp-main-btn {
  flex: 1; min-width: 0;
  display: flex; align-items: center; gap: 10px;
  background: transparent; border: none; cursor: pointer;
  padding: 4px; font-family: inherit; text-align: left; color: var(--text);
  border-radius: 8px;
}
.kp-main-btn:hover { background: #F8FAFF; }
.kp-row.selected .kp-main-btn:hover { background: transparent; }
.kp-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.kp-name { font-size: 15px; font-weight: 600; }
.kp-meta { font-size: 12.5px; color: var(--text-2); }
.kp-bar { display: block; height: 6px; background: #EDF0F4; border-radius: 3px; overflow: hidden; max-width: 340px; }
.kp-bar > span { display: block; height: 100%; background: var(--amber); border-radius: 3px; }
.kp-rate { font-size: 15px; font-weight: 700; color: var(--amber); min-width: 44px; text-align: right; }
.verify-btn { flex-shrink: 0; }
.verify-done {
  flex-shrink: 0; display: inline-flex; align-items: center; gap: 4px;
  font-size: 12.5px; font-weight: 600; color: var(--green);
}
</style>
