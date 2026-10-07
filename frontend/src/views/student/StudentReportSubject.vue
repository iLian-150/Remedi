<!-- 学生端：学习报告 · 科目详情（v0.6.0 从学习报告页拆出的独立页）
     入口：学习报告落地页点科目吊牌（播掉落动画后 router.push 到这里）；
     页头带「← 返回学习报告」按钮。本页内容即原报告页的页内展开详情：
       科目总览 → 知识点列表（四态）+ 验证面板 → 错题时间线 → 步骤诊断（跳诊断报告页）
     入场动画：内容从上方落下带一次小回弹（与吊牌掉落衔接）；prefers-reduced-motion 时无动画。
     深链：订正页「去验证」带 ?verify=<知识点名> 跳入，自动选中该知识点并打开验证面板。
     文案伦理：学生端用「待修复 / 反复出错 / 已订正待验证 / 已修复」，不出现「顽固」「置信度」。 -->
<template>
  <div class="page">
    <div class="page-head subject-head">
      <router-link to="/student/report" class="back-btn">
        <AppIcon name="chevron-left" :size="16" /> 返回学习报告
      </router-link>
      <h2>{{ subjectName }} · 学习报告</h2>
      <p class="page-sub">看看这个科目的进步轨迹：哪个知识点还没修好、错过几次、最近一次错在哪一步。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="!subj" class="card">
      <div class="empty">这个科目暂时还没有学习记录，先去作答几道题，报告就会慢慢长出来。</div>
    </div>

    <div v-else class="land-in">
      <!-- 一级：科目总览 -->
      <div class="card">
        <h3><AppIcon name="book" :size="18" /> {{ subjectName }}总览</h3>
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

      <!-- 二级 + 三级（双列）：左 知识点列表 | 右 验证面板 + 错题时间线 -->
      <div class="report-grid">
        <div class="card">
          <h3><AppIcon name="target" :size="18" /> 知识点明细</h3>
          <p class="card-sub">按错误率从高到低排。点知识点在右列看错题时间线；还没修复的可以点「去验证」做一道同类题。</p>
          <div v-if="!subj.knowledge_points.length" class="empty">这个科目暂时没有错题记录，继续保持。</div>
          <div v-for="kp in subj.knowledge_points" :key="kp.name" class="kp-block">
            <div class="kp-row" :class="{ selected: selectedKpName === kp.name }">
              <button type="button" class="kp-main-btn" @click="selectKp(kp)">
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
                @click="openVerify(kp)"
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
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
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

const subject = computed(() => String(route.params.subject || 'math'))
const subjectName = computed(() => SUBJECT_TEXT[subject.value] ?? subject.value)

const report = ref<SubjectReport[]>([])
const loading = ref(false)
const error = ref('')

const subj = computed<SubjectReport | null>(
  () => report.value.find((r) => r.subject === subject.value) ?? null
)

// ---------- 知识点选中 / 错题时间线 ----------
const selectedKpName = ref('')
const timeline = ref<KnowledgePointErrorItem[]>([])
const timelineLoading = ref(false)

/** 从最新报告数据里取选中的知识点（刷新报告后状态自动跟随） */
const selectedKp = computed<ReportKnowledgePoint | null>(
  () => subj.value?.knowledge_points.find((k) => k.name === selectedKpName.value) ?? null
)

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

async function selectKp(kp: ReportKnowledgePoint) {
  selectedKpName.value = kp.name
  await loadTimeline()
}

// ---------- 二次验证 ----------
const verifyKpName = ref('')

async function openVerify(kp: ReportKnowledgePoint) {
  await selectKp(kp)
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

/** 深链 ?verify=<知识点名>：在本科目找到就打开验证面板；属于别的科目则跳过去 */
async function applyVerifyDeepLink() {
  const want = typeof route.query.verify === 'string' ? route.query.verify : ''
  if (!want) return
  const kp = subj.value?.knowledge_points.find((k) => k.name === want)
  if (kp) {
    await openVerify(kp)
    return
  }
  for (const s of report.value) {
    if (s.subject !== subject.value && s.knowledge_points.some((k) => k.name === want)) {
      router.replace({ path: `/student/report/${s.subject}`, query: { verify: want } })
      break
    }
  }
}

onMounted(async () => {
  loading.value = true
  try {
    report.value = await student.fetchReport()
    await applyVerifyDeepLink()
  } catch (e) {
    error.value = '学习报告加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})

// 跨科目深链 replace 后组件不重挂载，靠 watch 重新应用深链
watch(
  () => route.params.subject,
  async () => {
    verifyKpName.value = ''
    selectedKpName.value = ''
    timeline.value = []
    await applyVerifyDeepLink()
  }
)
</script>

<style scoped>
.subject-head h2 { margin-top: 10px; }
.back-btn {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 13.5px; font-weight: 600; color: var(--primary);
  text-decoration: none; padding: 6px 12px 6px 8px;
  border: 1px solid #D7E3FA; border-radius: 999px; background: var(--primary-50);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.back-btn:hover { transform: translateY(-1px); box-shadow: var(--shadow); }

/* 入场：从上方落下，落定带一次小回弹（与落地页吊牌掉落衔接） */
.land-in { animation: land-drop 0.6s cubic-bezier(0.22, 1.15, 0.36, 1) both; }
@keyframes land-drop {
  0% { transform: translateY(-36px); opacity: 0; }
  55% { transform: translateY(6px); opacity: 1; }
  78% { transform: translateY(-2px); }
  100% { transform: translateY(0); opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .land-in { animation: none; }
  .back-btn { transition: none; }
}

.fix-progress { margin-top: 16px; }
.fix-progress-head { display: flex; justify-content: space-between; font-size: 13.5px; font-weight: 600; margin-bottom: 6px; }
.fix-bar { height: 10px; background: #EDF0F4; border-radius: 5px; overflow: hidden; }
.fix-bar > div { height: 100%; background: var(--green); border-radius: 5px; transition: width 0.3s; }
.fix-progress .hint { margin-top: 6px }

/* ---------- 双列详情：左知识点 / 右时间线 ---------- */
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
