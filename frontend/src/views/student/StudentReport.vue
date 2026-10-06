<!-- 学生端：学习报告（v0.2.1 新增）
     对应开题报告「学习记忆层 + 教学反馈层」，四级下钻：
       科目 → 知识点（状态/错误率） → 错题时间线（纵向） → 步骤诊断（跳现有诊断报告页定位到该次提交）
     数据源：GET /api/student/report、GET /api/student/report/knowledge-points/{name}/errors
     文案伦理：学生端用「待修复 / 反复出错 / 已加固」，不出现「顽固」「置信度」。 -->
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

      <div v-if="activeSubject" ref="detailRef">
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
            <p class="hint">出过错的知识点里，已经通过订正加固好的比例。</p>
          </div>
        </div>

        <!-- 二级：知识点列表 -->
        <div class="card">
          <h3><AppIcon name="target" :size="18" /> 知识点明细</h3>
          <p class="card-sub">按错误率从高到低排，点任意知识点可以展开它下面的错题时间线。</p>
          <div v-if="!subj.knowledge_points.length" class="empty">这个科目暂时没有错题记录，继续保持。</div>
          <div v-for="kp in subj.knowledge_points" :key="kp.name" class="kp-block">
            <button type="button" class="kp-row" @click="toggleKp(subj.subject, kp)">
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
              <AppIcon :name="expandedKey === kpKey(subj.subject, kp.name) ? 'chevron-down' : 'chevron-right'" :size="16" />
            </button>

            <!-- 三级：错题时间线 -->
            <div v-if="expandedKey === kpKey(subj.subject, kp.name)" class="kp-timeline">
              <div v-if="timelineLoading" class="loading" style="padding: 16px 0">加载错题时间线…</div>
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
import { useRouter } from 'vue-router'
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

const student = useStudentStore()
const router = useRouter()

const SUBJECT_TEXT: Record<string, string> = { math: '数学', english: '英语', physics: '物理', chemistry: '化学' }
const STATUS_TEXT: Record<KnowledgePointStatus, string> = {
  pending: '待修复',
  stubborn: '反复出错',
  fixed: '已加固'
}
const STATUS_BADGE: Record<KnowledgePointStatus, string> = {
  pending: 'badge-amber',
  stubborn: 'badge-red',
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

async function enterSubject(s: SubjectCard) {
  if (s.placeholder) return
  activeSubject.value = s.key
  await nextTick()
  detailRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const expandedKey = ref('')
const timeline = ref<KnowledgePointErrorItem[]>([])
const timelineLoading = ref(false)

function kpKey(subject: string, name: string): string {
  return `${subject}::${name}`
}

function fmtDate(t: string): string {
  return t.replace('T', ' ').slice(0, 10)
}
function fmtDateTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

async function toggleKp(subject: string, kp: ReportKnowledgePoint) {
  const key = kpKey(subject, kp.name)
  if (expandedKey.value === key) {
    expandedKey.value = ''
    return
  }
  expandedKey.value = key
  timeline.value = []
  timelineLoading.value = true
  try {
    timeline.value = await student.fetchKnowledgePointErrors(kp.name)
  } catch (e) {
    error.value = '错题时间线加载失败。'
    console.error(e)
  } finally {
    timelineLoading.value = false
  }
}

function gotoDiagnosis(submissionId: number) {
  router.push({ path: '/student/feedback', query: { submission_id: submissionId } })
}

onMounted(async () => {
  loading.value = true
  try {
    report.value = await student.fetchReport()
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
@media (prefers-reduced-motion: reduce) {
  .hang-wrap { animation: none; }
  .hang-card { transition: none; }
}

.fix-progress { margin-top: 16px; }
.fix-progress-head { display: flex; justify-content: space-between; font-size: 13.5px; font-weight: 600; margin-bottom: 6px; }
.fix-bar { height: 10px; background: #EDF0F4; border-radius: 5px; overflow: hidden; }
.fix-bar > div { height: 100%; background: var(--green); border-radius: 5px; transition: width 0.3s; }
.fix-progress .hint { margin-top: 6px; }

.kp-block { border-bottom: 1px solid #F1F3F6; }
.kp-block:last-child { border-bottom: none; }
.kp-row {
  width: 100%;
  display: flex; align-items: center; gap: 10px;
  background: transparent; border: none; cursor: pointer;
  padding: 12px 4px; font-family: inherit; text-align: left; color: var(--text);
}
.kp-row:hover { background: #F8FAFF; }
.kp-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.kp-name { font-size: 15px; font-weight: 600; }
.kp-meta { font-size: 12.5px; color: var(--text-2); }
.kp-bar { display: block; height: 6px; background: #EDF0F4; border-radius: 3px; overflow: hidden; max-width: 340px; }
.kp-bar > span { display: block; height: 100%; background: var(--amber); border-radius: 3px; }
.kp-rate { font-size: 15px; font-weight: 700; color: var(--amber); min-width: 44px; text-align: right; }
.kp-timeline { padding: 6px 4px 14px 10px; }
</style>
