<!-- 学生端：订正错题
     从错题本取可订正的错题（诊断产生的错题；自主收录题没有诊断记录不在此列），
     针对某条 error 提交订正，后端自动判定正误（is_correct：true/false/null）。
     v0.4.0 口径：订正成功只是「已订正」；响应带 can_verify 时在结果区给出
     入口，页内打开变式题面板（VerifyPanel）做二次验证，通过验证该知识点才
     算「已修复」（原先跳学习报告页验证，本次改造随报告纯化迁回本页；墙上方
     另有「待验证的知识点」汇总入口，KP 状态读 fetchReport 的四态口径）。
     本地 fixedIds 仅表示已订正。
     v0.9.0 曾在页内加订正日历；v0.9.1 日历迁入右侧栏（右栏在订正页切换为
     「订正日历」模式），选中日期经 store.correctionsDateFilter 与本页共享：
     本页顶部出现筛选状态条，「查看全部」清除；低置信度错题会在教师复核同时
     进入本页，并标记「老师复核中」。
     v0.9.3：选错题从下拉改成「便利贴墙」（CorrectionStickyWall）——一题一贴，
     点待订正的贴撕下后进入原修正工作区（三张卡与提交逻辑不变），返回后刚订正
     对的贴变已订正样式留在墙上；已订正的贴点开跳诊断详情。 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>订正错题</h2>
      <p class="page-sub">把错过的题重新做对，知识点就真正属于你了。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载错题中…</div>

    <template v-else>
      <p class="rail-note"><AppIcon name="calendar" :size="15" /> 订正日历在右侧栏，点选任意一天即可只看那天的错题。</p>

      <!-- 日期筛选状态栏（v0.9.1）：右侧栏订正日历选中某天时出现，与作业列表页同构 -->
      <div v-if="selectedDate" class="card filter-bar">
        <div class="filter-info">
          <span class="filter-title">正在看 {{ selectedDateLabel }} 的订正</span>
          <span class="filter-progress-text tnum">共 {{ errorList.length }} 条 · 待订正 {{ pendingCount }} 条</span>
        </div>
        <button class="btn secondary small" @click="clearDateFilter">查看全部</button>
      </div>

      <!-- 待验证的知识点（KP 维度入口）：错题都订正好了、还没做变式题验证的
           知识点汇总在这里，点按钮页内展开变式题面板完成验证 -->
      <div v-if="view === 'wall' && awaitingVerifyKps.length" class="card verify-kp-card">
        <h3><AppIcon name="target" :size="18" /> 待验证的知识点</h3>
        <p class="card-sub">这些知识点的错题已经全部订正好，再做对一道同类变式题，就能完成验证、真正修复。</p>
        <div v-for="kp in awaitingVerifyKps" :key="kp" class="verify-kp-row">
          <span class="badge badge-blue">{{ kp }}</span>
          <button class="btn small" @click="verifyKp = kp">做一道变式题，完成这个知识点的验证</button>
        </div>
        <VerifyPanel
          v-if="verifyKp"
          :key="`wall-${verifyKp}`"
          :knowledge-point="verifyKp"
          class="verify-panel-inline"
          @passed="onVerifyPassed"
          @close="verifyKp = ''"
        />
      </div>

      <!-- 便利贴墙（v0.9.3）：一题一贴，点待订正的贴撕下后进修正工作区；
           已订正的贴点开跳诊断详情。空态时墙上只留一张提示贴。 -->
      <CorrectionStickyWall
        v-if="view === 'wall'"
        :notes="wallNotes"
        @pick="onPickNote"
        @view="onViewNote"
      >
        <template #empty>
          <template v-if="!mistakes.length">
            太棒了，目前没有需要订正的题目，去 <router-link to="/student/assignments" class="empty-link">作业列表</router-link> 继续挑战吧。
          </template>
          <template v-else>这一天没有需要订正的错题，换一天看看，或者点上方「查看全部」。</template>
        </template>
      </CorrectionStickyWall>

      <template v-if="view === 'work' && selectedError">
        <div class="work-bar">
          <button class="btn secondary small inline-icon" @click="backToWall">
            <AppIcon name="chevron-left" :size="15" /> 返回便利贴墙
          </button>
        </div>
        <div class="card">
          <h3>题目回顾</h3>
          <!-- v0.13.9：原来这里只有出错的一步、看不到原题——改成完整回顾：
               原来的题目 → 我当时的作答（错步在原步骤里原地标出）→ 解析。
               v0.13.10：正确答案与标准解题过程不在订正前直接给出（用户口径），
               先自己想、自己改，判定结果会告诉你对不对 -->
          <div class="review-block">
            <span class="review-label">原来的题目</span>
            <p class="review-stem">{{ selectedError.question_stem || '题目内容暂未记录' }}</p>
            <a v-if="selectedError.image_url" class="review-img-link" :href="imageHref(selectedError.image_url)" target="_blank" rel="noreferrer">查看上传原图</a>
          </div>
          <div class="review-block">
            <span class="review-label">我当时的作答</span>
            <ol v-if="origSteps.length" class="orig-steps">
              <li v-for="st in origSteps" :key="st.seq" :class="origStepClass(st)">
                <span class="orig-seq">{{ st.seq }}</span>
                <span class="orig-text">{{ st.text }}</span>
                <span v-if="st.status === 'error'" class="orig-flag">出错在这里</span>
              </li>
            </ol>
            <p v-else-if="selectedError.step_text" class="step-text">第 {{ selectedError.step_seq ?? '?' }} 步：{{ selectedError.step_text }}（这一步出错了）</p>
            <p v-else class="detail">原来的作答步骤暂未记录。</p>
          </div>
          <p class="detail"><strong>解析：</strong>{{ sanitizeStudentCopy(selectedError.detail ?? '') }}</p>
          <p style="margin-top: 10px">
            <ErrorTypeBadge :type="selectedError.error_type" />
            <span class="badge badge-blue">{{ subjectName(selectedError.question_subject) }}</span>
            <span class="badge badge-blue">{{ selectedError.knowledge_point }}</span>
            <span v-if="selectedError.review_status === 'pending'" class="badge badge-amber">老师复核中</span>
            <span v-if="fixedIds.has(selectedError.id)" class="badge badge-green">已订正</span>
            <span v-else-if="selectedError.is_stubborn" class="badge badge-amber">需要加固</span>
          </p>
        </div>

        <div class="card">
          <h3>我的订正</h3>
          <div class="form-row">
            <label>写出这一步的正确内容</label>
            <input v-model="content" type="text" :placeholder="correctionPlaceholder" />
          </div>
          <button class="btn" :disabled="submitting || !content.trim()" @click="submit">
            {{ submitting ? '判定中…' : '提交订正' }}
          </button>
        </div>

        <div v-if="result" class="card">
          <h3>判定结果</h3>
          <p v-if="result.is_correct === true"><span class="badge badge-green">订正成功</span></p>
          <p v-else-if="result.is_correct === false"><span class="badge badge-amber">再想一想</span></p>
          <p v-else><span class="badge badge-gray">暂时无法自动判定</span></p>
          <p class="note">
            {{
              result.is_correct === true
                ? '做得好，这条错题订正对了。'
                : result.is_correct === false
                  ? '这次还不太对，再看看解析，换个思路试一次。'
                  : '暂时无法自动判定，请将这条订正内容交给老师确认。'
            }}
          </p>
          <p class="note hint">{{ result.note }}</p>
          <!-- 订正成功且该知识点待验证 → 页内打开变式题面板完成验证（通过才算已修复） -->
          <div v-if="result.can_verify && !justVerified" class="verify-cta">
            <p>再做对一道同类题验证一下，这个知识点就真正修复啦。</p>
            <button class="btn small inline-icon" @click="openResultVerify">
              <AppIcon name="target" :size="15" /> 做一道变式题，完成这个知识点的验证
            </button>
          </div>
          <p v-else-if="result.can_verify && justVerified" class="verify-done-note">
            <AppIcon name="check" :size="15" /> 这个知识点的验证已经完成了，它真正修复啦。
          </p>
          <VerifyPanel
            v-if="verifyKp"
            :key="`work-${verifyKp}`"
            :knowledge-point="verifyKp"
            class="verify-panel-inline"
            @passed="onVerifyPassed"
            @close="verifyKp = ''"
          />
          <div class="result-actions">
            <button class="btn secondary small inline-icon" @click="backToWall">
              <AppIcon name="chevron-left" :size="15" /> 回到便利贴墙
            </button>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStudentStore } from '../../stores/student'
import { useAuthStore } from '../../stores/auth'
import type { CorrectionResult, GradingError, StepDiagnosis, StudentMistake } from '../../api/types'
import { sanitizeStudentCopy } from '../../utils/errorType'
import { getFixedErrorIds, markErrorFixed } from '../../utils/correctionTracker'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import AppIcon from '../../components/icons/AppIcon.vue'
import VerifyPanel from '../../components/VerifyPanel.vue'
import CorrectionStickyWall, { type CorrectionNote } from '../../components/CorrectionStickyWall.vue'

const student = useStudentStore()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

/** 全部可订正错题（原始错题本条目，仅诊断产生的；自主收录题无诊断记录不能订正） */
const mistakes = ref<StudentMistake[]>([])
const selectedErrorId = ref<number | ''>('')
/** 当前视图：wall 便利贴墙 / work 修正工作区（点贴撕下后进入，v0.9.3） */
const view = ref<'wall' | 'work'>('wall')
/** 订正日历选中的日期（yyyy-mm-dd，空 = 全部）：v0.9.1 起由右侧栏订正日历写入
 * store.correctionsDateFilter，本页只读消费（筛选状态条与列表都据此响应） */
const selectedDate = computed(() => student.correctionsDateFilter)
const content = ref('')
const result = ref<CorrectionResult | null>(null)
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const fixedIds = ref<Set<number>>(new Set())

/** 错题所属提交的日期键：优先后端 submitted_at，缺失时用错题产生时间兜底 */
function mistakeDateKey(item: StudentMistake): string {
  return (item.submitted_at ?? item.created_at).slice(0, 10)
}

const selectedDateLabel = computed(() => {
  if (!selectedDate.value) return ''
  const [y, m, d] = selectedDate.value.split('-')
  return `${y} 年 ${Number(m)} 月 ${Number(d)} 日`
})

/** 当前可见错题原条目（选了日期就只剩那天的），贴墙与工作区都消费这份 */
const visibleMistakes = computed(() =>
  mistakes.value.filter((item) => !selectedDate.value || mistakeDateKey(item) === selectedDate.value)
)
const errorList = computed<GradingError[]>(() => visibleMistakes.value.map(toGradingError))

/** 贴面日期文案：如「10月7日」 */
function dateLabelOf(item: StudentMistake): string {
  const [, m, d] = mistakeDateKey(item).split('-')
  return `${Number(m)}月${Number(d)}日`
}

/** 便利贴墙数据：一题一贴 */
const wallNotes = computed<CorrectionNote[]>(() =>
  visibleMistakes.value.map((item) => ({
    errorId: item.id,
    submissionId: item.submission_id,
    stem: item.question_stem || item.step_text || '',
    stepText: item.step_text && item.step_text !== item.question_stem ? item.step_text : '',
    knowledgePoint: item.knowledge_point,
    errorType: item.error_type,
    reviewStatus: item.review_status,
    assignmentTitle: item.assignment_title,
    dateLabel: dateLabelOf(item),
    isFixed: fixedIds.value.has(item.id),
    isStubborn: item.is_stubborn
  }))
)

/** 点待订正的贴（撕下动画播完）→ 进入该题修正工作区 */
function onPickNote(errorId: number) {
  selectedErrorId.value = errorId
  onSelect()
  view.value = 'work'
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

/** 点已订正的贴 → 沿用全站口径跳诊断详情 */
function onViewNote(submissionId: number) {
  router.push({ path: '/student/diagnosis', query: { submission_id: submissionId } })
}

/** 返回便利贴墙（fixedIds 已在提交成功时更新，刚订正对的贴随之变已订正样式） */
function backToWall() {
  view.value = 'wall'
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

/** 筛选状态条的待订正计数（当前可见里还没订正对的） */
const pendingCount = computed(() => errorList.value.filter((e) => !fixedIds.value.has(e.id)).length)

function clearDateFilter() {
  student.setCorrectionsDateFilter('')
}

// 右栏日历点选（含再点同一天取消）→ store 筛选变化 → 贴墙只剩当天的贴；
// 若正在修正的题被筛掉，退回贴墙（墙面始终与筛选一致）
watch(selectedDate, () => syncSelection())

function syncSelection() {
  if (view.value === 'work' && !errorList.value.some((e) => e.id === selectedErrorId.value)) {
    view.value = 'wall'
    selectedErrorId.value = ''
    onSelect()
  }
}

// v0.13.9：工作区直接消费错题原条目（StudentMistake）——题目回顾要用的原题、
// 正确答案、标准解题过程、原图都在原条目上，经 toGradingError 映射后会丢掉
const selectedError = computed(() => visibleMistakes.value.find((e) => e.id === selectedErrorId.value) ?? null)
const correctionPlaceholder = computed(() => selectedError.value?.question_subject === 'math'
  ? '例如：2x=7-3'
  : '写出订正后的正确步骤、结论或答案')
const subjectNames: Record<string, string> = {
  math: '数学', english: '英语', english_exercise: '英语练习', physics: '物理',
  chemistry: '化学', biology: '生物', chinese: '语文', history: '历史',
  geography: '地理', politics: '道德与法治', computer_science: '信息科技',
  art: '艺术', music: '音乐', pe: '体育', other: '其他学科'
}
function subjectName(subject: string) { return subjectNames[subject] || subject || '其他学科' }

// v0.13.9：题目回顾要展示「我当时的作答」全文——错题条目里只有出错的那一步，
// 完整原步骤在提交详情里（每步带判定状态），选中错题时按 submission_id 拉一次；
// 拉不到就降级为只显示出错步骤（模板里的 v-else 分支）
const origSteps = ref<StepDiagnosis[]>([])
let origLoadToken = 0
async function loadOrigSteps() {
  const err = selectedError.value
  origSteps.value = []
  if (!err) return
  const token = ++origLoadToken
  try {
    const detail = await student.fetchSubmissionDetail(err.submission_id)
    if (token !== origLoadToken) return
    // seq=0 是题干伪步骤，已在「原来的题目」里单独展示，这里只列作答步
    origSteps.value = (detail.steps ?? []).filter((s) => s.status !== 'stem')
  } catch {
    if (token === origLoadToken) origSteps.value = []
  }
}
watch(selectedError, () => { void loadOrigSteps() })

function origStepClass(st: StepDiagnosis) {
  return {
    'is-error': st.status === 'error',
    'is-dim': st.status === 'skipped' || st.status === 'unparseable'
  }
}

/** 原图链接（与错题本同口径：相对路径按 API 基址补全） */
function imageHref(value: string) {
  const base = import.meta.env.VITE_API_BASE_URL || ''
  return base ? `${base.replace(/\/+$/, '')}${value}` : value
}

// ---------- 二次验证（迁入本页：报告纯化后验证入口只在订正流里） ----------
/** 当前打开了变式题面板的知识点（空 = 未打开）；墙面待验证区与结果区共用这一个状态 */
const verifyKp = ref('')
/** 本次订正后刚在页内完成了该知识点的验证（结果区 CTA 随之换成完成提示） */
const justVerified = ref(false)
/** 待验证知识点名单：读学习报告四态口径（status === 'awaiting_verify'），跨科目汇总 */
const awaitingVerifyKps = ref<string[]>([])

async function loadAwaitingVerifyKps() {
  try {
    const reportData = await student.fetchReport()
    const names = new Set<string>()
    for (const s of reportData) {
      for (const kp of s.knowledge_points) {
        if (kp.status === 'awaiting_verify') names.add(kp.name)
      }
    }
    awaitingVerifyKps.value = [...names]
  } catch (e) {
    console.error(e)
  }
}

/** 结果区入口：为刚订正对的这条错题所属知识点打开变式题面板 */
function openResultVerify() {
  const kp = result.value?.knowledge_point ?? selectedError.value?.knowledge_point ?? ''
  if (kp) verifyKp.value = kp
}

/** 验证通过：刷新待验证名单（该知识点转为已修复后自动从名单消失） */
async function onVerifyPassed() {
  justVerified.value = true
  await loadAwaitingVerifyKps()
}

function onSelect() {
  content.value = ''
  result.value = null
  justVerified.value = false
}

async function submit() {
  if (!selectedErrorId.value) return
  submitting.value = true
  error.value = ''
  result.value = null
  justVerified.value = false
  verifyKp.value = ''
  try {
    result.value = await student.submitCorrection({
      error_id: Number(selectedErrorId.value),
      content: content.value.trim()
    })
    // 订正成功 → 本地标记已修复（契约无订正记录查询接口，仅本机可知）
    if (result.value.is_correct === true && auth.user) {
      markErrorFixed(auth.user.id, Number(selectedErrorId.value))
      fixedIds.value = getFixedErrorIds(auth.user.id)
    }
  } catch (e) {
    error.value = '订正提交失败：' + errDetail(e)
    console.error(e)
  } finally {
    submitting.value = false
  }
}

function errDetail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof d === 'string' ? d : '请稍后重试。'
}

onMounted(async () => {
  loading.value = true
  try {
    if (auth.user) fixedIds.value = getFixedErrorIds(auth.user.id)
    // 可订正错题的拉取/合并/过滤口径在 store 里与右栏订正日历共用一份
    mistakes.value = await student.fetchCorrectableMistakes()
    // 待验证知识点名单（墙上方 KP 维度验证入口的数据来源，失败不挡页面）
    void loadAwaitingVerifyKps()
    if (auth.user) {
      const serverFixed = mistakes.value.filter((item) => item.latest_correction?.is_correct === true).map((item) => item.id)
      fixedIds.value = new Set([...fixedIds.value, ...serverFixed])
    }
    // 深链带 error_id 时直接进该题修正工作区（沿用既有深链口径）；否则停在贴墙
    const requestedId = Number(route.query.error_id)
    if (errorList.value.some((item) => item.id === requestedId)) {
      selectedErrorId.value = requestedId
      view.value = 'work'
    }
  } catch (e) {
    error.value = '错题加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})

function toGradingError(item: StudentMistake): GradingError {
  return {
    id: item.id,
    submission_id: item.submission_id,
    step_seq: item.step_seq ?? 0,
    step_text: item.step_text || item.question_stem,
    knowledge_point: item.knowledge_point,
    error_type: item.error_type,
    confidence: 0,
    is_stubborn: item.is_stubborn,
    detail: item.detail ?? '',
    teacher_corrected: false,
    teacher_note: null,
    created_at: item.created_at
  }
}
</script>

<style scoped>
/* 右栏提示与筛选状态条：与作业列表页同构（v0.9.1） */
.rail-note {
  display: flex; align-items: center; gap: 7px;
  font-size: 13.5px; color: var(--text-2);
  background: var(--primary-50); border: 1px solid #DBEAFE; border-radius: 10px;
  padding: 10px 14px; margin-bottom: 16px;
}
.filter-bar {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  margin-bottom: 16px; padding: 14px 18px;
}
.filter-info { display: flex; align-items: center; gap: 14px; flex: 1; min-width: 240px; flex-wrap: wrap; }
.filter-title { font-size: 15px; font-weight: 700; }
.filter-progress-text { font-size: 13.5px; color: var(--text-2); }
.step-text { font-size: 15px; font-weight: 600; margin-bottom: 8px; }
.detail { font-size: 14px; color: var(--text-2); }
/* v0.13.9：题目回顾完整版——原题 / 原作答（错步原地标红）/ 正确答案 / 标准过程 */
.review-block { margin-bottom: 14px; }
.review-label { display: block; font-size: 12px; font-weight: 700; color: var(--text-3); letter-spacing: .4px; margin-bottom: 5px; }
.review-stem { font-size: 16px; font-weight: 600; line-height: 1.65; }
.review-img-link { display: inline-block; margin-top: 6px; font-size: 13px; color: var(--primary); font-weight: 600; }
.orig-steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.orig-steps li { display: flex; align-items: baseline; gap: 9px; padding: 7px 10px; border-radius: 9px; background: var(--bg); font-size: 14px; }
.orig-steps li.is-error { background: #FEF2F2; box-shadow: inset 0 0 0 1.5px #DC2626; }
.orig-steps li.is-dim { opacity: .55; }
.orig-seq { flex-shrink: 0; width: 20px; height: 20px; border-radius: 50%; background: #fff; border: 1px solid var(--border); font-size: 12px; font-weight: 700; color: var(--text-2); display: inline-flex; align-items: center; justify-content: center; transform: translateY(2px); }
.orig-steps li.is-error .orig-seq { background: #DC2626; border-color: transparent; color: #fff; }
.orig-text { flex: 1; line-height: 1.55; word-break: break-word; }
.orig-flag { flex-shrink: 0; font-size: 12px; font-weight: 700; color: #DC2626; }
.note { margin-top: 8px; font-size: 14px; color: var(--text); }
.note.hint { color: var(--text-3); font-size: 13px; }
.verify-cta {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  background: var(--primary-50); border: 1px solid #DBEAFE; border-radius: 10px;
  padding: 11px 14px; margin-top: 12px; font-size: 14px;
}
/* 页内变式题面板与验证入口（报告纯化后迁入本页） */
.verify-panel-inline { margin-top: 14px; }
.verify-done-note {
  display: flex; align-items: center; gap: 7px;
  margin-top: 12px; font-size: 14px; font-weight: 600; color: var(--green);
}
.verify-kp-card .card-sub { font-size: 13.5px; color: var(--text-2); margin: -4px 0 10px; }
.verify-kp-row {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 8px 0; border-bottom: 1px solid #F1F3F6;
}
.verify-kp-row:last-of-type { border-bottom: none; }
/* 修正工作区的返回入口与判定结果里的回墙按钮（v0.9.3） */
.work-bar { margin-bottom: 16px; }
.result-actions { margin-top: 14px; }
.empty-link { color: var(--primary); font-weight: 600; }
</style>
