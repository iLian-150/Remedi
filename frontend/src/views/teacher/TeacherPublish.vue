<!-- 教师端：发布作业（v0.2.0 新增；v0.5.0 双模式）
     发布分两种模式（v0.5.0）：
       - 线上作业：手动录题 / 逐题拍照识别，学生逐题拍照批改（原流程）。
       - 线下作业 · 练习册：从练习册知识库选一本（可现场上传整本 PDF）+ 填页码范围 + 截止时间，
         再拍照上传题目页识别成草稿题，教师检查修改后发布；学生作答方式与线上完全一致。
     契约：POST /api/teacher/assignments（4.7，v0.5.0 加 mode/workbook_id/page_range/deadline）、
           练习册知识库 4.15~4.17、拍照识别 4.9。本轮题目仍只支持数学。 -->
<template>
  <div class="page publish-page">
    <div class="page-head">
      <h2>发布作业</h2>
      <p class="page-sub">{{ step === 'choose' ? '先选一种发布方式，点进去再填内容。发布后学生端立即可见。' : '填写作业内容后点底部「发布」。返回上一级不会清空已填内容。' }}</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="ok" class="ok-msg">发布成功，正在跳转到作业列表…</div>

    <!-- 第一级：选择发布方式（v0.12.0 两级化：点卡进入第二级表单，不再同页堆叠） -->
    <template v-if="step === 'choose'">
      <div class="mode-grid choose-grid">
        <button type="button" class="mode-card" @click="chooseMode('online')">
          <span class="mode-icon"><AppIcon name="edit" :size="22" /></span>
          <span class="mode-name">线上作业</span>
          <span class="mode-desc">在这里逐题录入（或拍照识别）题目，学生在系统里在线作答、逐步批改。</span>
          <span class="mode-enter">进入发布 <AppIcon name="arrow-right" :size="15" /></span>
        </button>
        <button type="button" class="mode-card" @click="chooseMode('offline')">
          <span class="mode-icon"><AppIcon name="book" :size="22" /></span>
          <span class="mode-name">线下作业 · 练习册</span>
          <span class="mode-desc">作业来自纸质练习册：选一本练习册、写清页码，拍下题目页识别成题，学生照着练习册做、拍照提交。</span>
          <span class="mode-enter">进入发布 <AppIcon name="arrow-right" :size="15" /></span>
        </button>
      </div>
      <p class="choose-hint">两种方式发布的都是数学作业，批改与审核流程完全一致。</p>
    </template>

    <!-- 第二级：发布表单 -->
    <template v-if="step === 'form'">
    <div class="form-topbar">
      <button type="button" class="btn ghost inline-icon back-btn" @click="backToChoose">
        <AppIcon name="chevron-left" :size="16" /> 重新选择发布方式
      </button>
      <span class="mode-chip"><AppIcon :name="mode === 'online' ? 'edit' : 'book'" :size="14" /> {{ mode === 'online' ? '线上作业' : '线下作业 · 练习册' }}</span>
    </div>

    <!-- 线下模式：练习册与页码 -->
    <div v-if="mode === 'offline'" class="card">
      <h3>练习册与范围</h3>
      <div class="form-row">
        <label>选择练习册（知识库）</label>
        <div class="wb-row">
          <select v-model="workbookId" :disabled="!workbooks.length">
            <option value="">{{ workbooks.length ? '请选择一本练习册…' : '知识库还是空的，先上传一本吧' }}</option>
            <option v-for="w in workbooks" :key="w.id" :value="w.id">{{ w.title }}</option>
          </select>
          <button class="btn small secondary inline-icon" :disabled="uploadingWb" @click="wbFileRef?.click()">
            <AppIcon name="plus" :size="14" /> {{ uploadingWb ? '上传中…' : '上传练习册 PDF' }}
          </button>
          <a
            v-if="selectedWorkbook"
            class="btn small secondary inline-icon"
            :href="selectedWorkbook.file_url"
            target="_blank"
            rel="noopener"
          >
            <AppIcon name="file" :size="14" /> 查看 PDF
          </a>
          <button
            v-if="selectedWorkbook"
            class="btn small danger-outline"
            @click="removeWorkbook"
          >
            {{ confirmDeleteWb ? '确认删除这本？' : '删除这本' }}
          </button>
        </div>
        <input ref="wbFileRef" type="file" accept="application/pdf" hidden @change="onWorkbookFile" />
        <p class="hint" style="margin-top: 6px">把整本练习册的 PDF 传进知识库，以后发布线下作业直接选，不用重复上传（单个文件 ≤30MB）。</p>
        <!-- 练习册封面缩略图条（v0.6.0）：点封面直接选中，与上方下拉同步 -->
        <div v-if="workbooks.length" class="wb-strip">
          <button
            v-for="w in workbooks"
            :key="w.id"
            type="button"
            class="wb-thumb"
            :class="{ active: Number(workbookId) === w.id }"
            :title="w.title"
            @click="workbookId = w.id"
          >
            <img v-if="w.cover_url" :src="w.cover_url" :alt="w.title" />
            <span v-else class="wb-thumb-spine"><AppIcon name="book" :size="18" /></span>
            <span class="wb-thumb-name">{{ w.title }}</span>
          </button>
        </div>
      </div>
      <div class="grid-2">
        <div class="form-row">
          <label>页码 / 题号范围</label>
          <input v-model="pageRange" type="text" placeholder="例如：第 12-14 页 第 1-8 题" maxlength="64" />
        </div>
        <div class="form-row">
          <label>截止时间（选填）</label>
          <input v-model="deadline" type="datetime-local" />
        </div>
      </div>
    </div>

    <div class="card">
      <h3>基本信息</h3>
      <div class="form-row">
        <label>作业标题</label>
        <input v-model="title" type="text" :placeholder="mode === 'offline' ? '例如：练习册 P12-14 勾股定理练习' : '例如：第二周数学作业'" maxlength="128" />
      </div>
      <div class="grid-2">
        <div class="form-row">
          <label>学科</label>
          <select v-model="subject" disabled>
            <option value="math">数学</option>
          </select>
          <p class="hint" style="margin-top: 6px">目前专注数学作业，支持拍照批改与逐步诊断。</p>
        </div>
        <div class="form-row">
          <label>作业总分（满分）</label>
          <div class="score-input-row">
            <input v-model.number="totalScore" type="number" min="1" max="10000" step="1" class="score-input" />
            <span class="hint">分 · AI 按步骤对错打分，待审核里可改分；每题满分按下方的「分值占比」折算。</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 线下模式：拍照上传题目页，一次识别成一道草稿题 -->
    <div v-if="mode === 'offline'" class="card offline-photo-card">
      <h3><AppIcon name="camera" :size="18" /> 拍照上传题目页</h3>
      <p class="card-sub">把练习册上要做的题目拍下来，识别后会生成一道草稿题填到下方，检查修改后就能发布。多道题可以连拍多次。</p>
      <button class="btn inline-icon" :disabled="appendRecognizing" @click="pickPhotoAppend">
        <AppIcon name="camera" :size="16" /> {{ appendRecognizing ? '识别中…' : '拍一页题目页' }}
      </button>
    </div>

    <div v-for="(q, idx) in questions" :key="idx" class="card" :class="{ 'q-suspect': showResult(q) && q.check_status === 'suspect' }">
      <div class="q-head">
        <h3 style="margin-bottom: 0">第 {{ idx + 1 }} 题 · 数学</h3>
        <div class="q-actions">
          <button class="btn small secondary inline-icon" :disabled="q.recognizing" @click="pickPhoto(idx)">
            <AppIcon name="camera" :size="15" /> {{ q.recognizing ? '识别中…' : '拍照识别题目' }}
          </button>
          <button class="btn small danger" :disabled="questions.length === 1" @click="questions.splice(idx, 1)">删除本题</button>
        </div>
      </div>
      <p v-if="q.recognized" class="ok-msg" style="margin-bottom: 12px">已通过照片识别填入，请检查题干与标准步骤是否正确，可直接修改后再发布。</p>
      <div class="form-row">
        <label>题干</label>
        <textarea v-model="q.prompt" rows="2" placeholder="例如：解方程：3x-5=10"></textarea>
      </div>
      <div class="grid-q-meta">
        <div class="form-row">
          <label>知识点</label>
          <input v-model="q.knowledge_point" type="text" placeholder="例如：一元一次方程" maxlength="64" />
        </div>
        <div class="form-row">
          <label>分值占比（占总分的百分比）</label>
          <div class="score-input-row">
            <input
              v-model.number="q.weight_pct"
              type="number" min="0" max="100" step="0.5"
              class="score-input" placeholder="均分"
            />
            <span class="hint">
              % · 本题满分约 {{ fmtScore(questionMax(q)) }} 分<template v-if="q.weight_pct === null || q.weight_pct === undefined">（留空按题数均分）</template>
            </span>
          </div>
        </div>
      </div>
      <div class="grid-q-body">
        <div class="form-row">
          <label>标准解题步骤（选填，每行一步，含第一步原式，供批改参考）</label>
          <textarea v-model="q.standard_steps_text" rows="5" placeholder="3x-5=10&#10;3x=10+5&#10;3x=15&#10;x=5"></textarea>
        </div>
        <div class="form-row">
          <div class="answer-label-row">
            <label>参考答案（选填）</label>
            <button
              type="button"
              class="btn small secondary inline-icon"
              :disabled="q.check_status === 'checking' || !q.prompt.trim() || !q.reference_answer.trim()"
              @click="checkOne(idx)"
            >
              <AppIcon name="sparkles" :size="13" /> {{ q.check_status === 'checking' ? '验算中…' : 'AI 验算' }}
            </button>
          </div>
          <input v-model="q.reference_answer" type="text" placeholder="例如：x=5" />
          <p v-if="q.check_status === 'checking'" class="check-note muted">正在验算这道题的参考答案…</p>
          <p v-else-if="showResult(q) && q.check_status === 'ok'" class="check-note ok" :title="q.check_detail">
            <span class="check-ic"><AppIcon name="check" :size="13" /></span> AI 验算无误
          </p>
          <p v-else-if="showResult(q) && q.check_status === 'suspect'" class="check-note warn">
            <span class="check-ic"><AppIcon name="alert" :size="13" /></span>
            <span>参考答案可能有误：{{ q.check_detail }}（只是提醒，仍可照常发布）</span>
          </p>
          <p class="hint" style="margin-top: 8px">标准步骤是批改的参照系，写得越完整，步骤诊断越准。</p>
        </div>
      </div>
    </div>

    <input ref="photoRef" type="file" accept="image/jpeg,image/png,image/webp" hidden @change="onPhotoChange" />
    <!-- 分值占比合计（评分系统）：只统计会真正发布的题（题干或知识点已填） -->
    <div class="card weight-bar">
      <span class="weight-sum" :class="{ bad: !weightSumOk }">
        分值占比合计 <b class="tnum">{{ fmtScore(weightSum) }}%</b>
        <template v-if="weightSumOk">，正好 100%</template>
        <template v-else-if="weightSum < 100">，还差 {{ fmtScore(100 - weightSum) }}%</template>
        <template v-else>，超出了 {{ fmtScore(weightSum - 100) }}%</template>
      </span>
      <span class="hint">没填占比的题按「100 ÷ 题数」计入合计；合计不是 100% 时不能发布，避免各题满分加起来超过总分。</span>
      <button type="button" class="btn small secondary" @click="distributeEvenly">一键均分</button>
    </div>
    <div class="toolbar publish-actions">
      <button class="btn secondary inline-icon" @click="addQuestion"><AppIcon name="plus" :size="15" /> 添加一题</button>
      <span class="weight-mini" :class="{ bad: !weightSumOk }">分值占比合计 <b class="tnum">{{ fmtScore(weightSum) }}%</b><template v-if="!weightSumOk">（需 100%）</template></span>
      <span class="spacer"></span>
      <button class="btn" :disabled="submitting || checkingAll" @click="submit">
        {{ checkingAll ? '正在验算参考答案…' : submitting ? '发布中…' : mode === 'offline' ? '发布线下作业' : '发布作业' }}
      </button>
    </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../api/client'
import { useTeacherStore } from '../../stores/teacher'
import type { TeacherAssignmentInput, Workbook } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'

const teacher = useTeacherStore()
const router = useRouter()
const route = useRoute()

interface QuestionForm {
  prompt: string
  knowledge_point: string
  standard_steps_text: string
  reference_answer: string
  weight_pct: number | null   // 评分系统：分值占比 %；null = 留空（按题数均分）
  recognized: boolean   // 是否刚通过照片识别填入（展示检查提示）
  recognizing: boolean  // 识别请求进行中
  // 参考答案 AI 验算（v0.9.3）：check_stamp 是验算时「题干+答案」的指纹，
  // 老师改了题干或答案后指纹对不上，旧验算标记自动不显示
  check_status: 'idle' | 'checking' | 'ok' | 'suspect' | 'unknown'
  check_detail: string
  check_stamp: string
}

const mode = ref<'online' | 'offline'>('online')
// 两级导航（v0.12.0）：choose = 选发布方式；form = 填发布表单。两级同组件，
// 返回上一级不清空已填内容；选方式时把 mode 写进 query，刷新/书架深链直达表单级。
const step = ref<'choose' | 'form'>('choose')

function chooseMode(m: 'online' | 'offline') {
  mode.value = m
  step.value = 'form'
  router.replace({ query: { ...route.query, mode: m } })
  window.scrollTo({ top: 0 })
}

function backToChoose() {
  step.value = 'choose'
  window.scrollTo({ top: 0 })
}
const title = ref('')
const subject = ref<'math'>('math')
const totalScore = ref(100)   // 评分系统：作业总分（满分），默认 100
const blankQuestion = (): QuestionForm => ({
  prompt: '', knowledge_point: '', standard_steps_text: '', reference_answer: '',
  weight_pct: null,
  recognized: false, recognizing: false,
  check_status: 'idle', check_detail: '', check_stamp: ''
})
const questions = ref<QuestionForm[]>([blankQuestion()])
const submitting = ref(false)
const checkingAll = ref(false)  // 发布前批量验算进行中（v0.9.3）
const error = ref('')
const ok = ref(false)

function errMsg(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof d === 'string' ? d : fallback
}

function addQuestion() {
  questions.value.push(blankQuestion())
}

// ---------- 评分系统：分值占比合计与校验 ----------
// 口径与后端一致：没填占比的题按「100 ÷ 会真正发布的题数」均分。
// 合计必须 = 100%（容差 0.5），否则各题满分加起来会超过/不足作业总分，发布拦截。

function fmtScore(v: number): string {
  return String(Math.round(v * 10) / 10)
}

/** 会真正发布的题目（题干或知识点已填），与 submit 的 valid 口径一致 */
const inPlayQuestions = computed(() =>
  questions.value.filter((q) => q.prompt.trim() || q.knowledge_point.trim())
)

function effectivePct(q: QuestionForm, n: number): number {
  const v = q.weight_pct
  if (v === null || v === undefined || Number.isNaN(Number(v))) return n ? 100 / n : 0
  return Number(v)
}

/** 本题满分（按生效占比折算），供题行内实时展示 */
function questionMax(q: QuestionForm): number {
  const n = inPlayQuestions.value.length || questions.value.length || 1
  return ((Number(totalScore.value) || 0) * effectivePct(q, n)) / 100
}

const weightSum = computed(() => {
  const list = inPlayQuestions.value
  if (!list.length) return 0
  const n = list.length
  return list.reduce((s, q) => s + effectivePct(q, n), 0)
})
const weightSumOk = computed(() => Math.abs(weightSum.value - 100) <= 0.5)

/** 一键均分：把 100% 平均写进每道会发布的题（最后一题吃掉小数尾差，合计恰好 100） */
function distributeEvenly() {
  const list = inPlayQuestions.value.length ? inPlayQuestions.value : questions.value
  const n = list.length
  if (!n) return
  const base = Math.floor((100 / n) * 10) / 10
  list.forEach((q, i) => {
    q.weight_pct = i === n - 1 ? Math.round((100 - base * (n - 1)) * 10) / 10 : base
  })
}

// ---------- 参考答案 AI 验算（v0.9.3）：只提醒、永不拦截发布 ----------

interface AnswerCheckResult {
  status: 'ok' | 'suspect' | 'unknown'
  detail: string
  method: 'sympy' | 'llm' | 'none'
}

/** 验算指纹：题干或答案被改过后，旧验算结果视为过期、不再显示 */
function stampOf(q: QuestionForm): string {
  return `${q.prompt.trim()}\n${q.reference_answer.trim()}`
}

function showResult(q: QuestionForm): boolean {
  return q.check_stamp !== '' && q.check_stamp === stampOf(q)
}

async function runCheck(q: QuestionForm): Promise<void> {
  q.check_stamp = stampOf(q)
  q.check_status = 'checking'
  q.check_detail = ''
  try {
    const { data } = await api.post<AnswerCheckResult>('/api/teacher/questions/check-answer', {
      stem: q.prompt.trim(),
      reference_answer: q.reference_answer.trim(),
      knowledge_point: q.knowledge_point.trim() || undefined
    })
    q.check_status = data.status
    q.check_detail = data.detail
  } catch (e) {
    // 验算接口异常按 unknown 处理：不显示任何标记，更不能挡住发布
    q.check_status = 'unknown'
    q.check_detail = ''
    console.error(e)
  }
}

async function checkOne(idx: number) {
  const q = questions.value[idx]
  if (q) await runCheck(q)
}

// ---------- 练习册知识库（v0.5.0） ----------
const workbooks = ref<Workbook[]>([])
const workbookId = ref<number | ''>('')
const pageRange = ref('')
const deadline = ref('')
const wbFileRef = ref<HTMLInputElement | null>(null)
const uploadingWb = ref(false)
const confirmDeleteWb = ref(false)

const selectedWorkbook = computed(() => workbooks.value.find((w) => w.id === Number(workbookId.value)) ?? null)

async function loadWorkbooks() {
  try {
    workbooks.value = await teacher.fetchWorkbooks()
  } catch (e) {
    console.error(e)
  }
}

async function onWorkbookFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
    error.value = '练习册只支持 PDF 文件。'
    return
  }
  if (file.size > 30 * 1024 * 1024) {
    error.value = 'PDF 太大了（超过 30MB），请压缩后再传。'
    return
  }
  uploadingWb.value = true
  error.value = ''
  try {
    const wb = await teacher.uploadWorkbook(file)
    workbooks.value.unshift(wb)
    workbookId.value = wb.id
    confirmDeleteWb.value = false
  } catch (err) {
    error.value = '练习册上传失败：' + errMsg(err, '请稍后重试。')
    console.error(err)
  } finally {
    uploadingWb.value = false
  }
}

async function removeWorkbook() {
  const wb = selectedWorkbook.value
  if (!wb) return
  if (!confirmDeleteWb.value) {
    confirmDeleteWb.value = true
    setTimeout(() => (confirmDeleteWb.value = false), 3000)
    return
  }
  try {
    await teacher.deleteWorkbook(wb.id)
    workbooks.value = workbooks.value.filter((w) => w.id !== wb.id)
    if (Number(workbookId.value) === wb.id) workbookId.value = ''
    confirmDeleteWb.value = false
  } catch (err) {
    error.value = '练习册删除失败：' + errMsg(err, '请稍后重试。')
    console.error(err)
  }
}

// ---------- 拍照识别题目（v0.2.1）：识别结果填入当前题行，教师检查后再发布 ----------
const photoRef = ref<HTMLInputElement | null>(null)
const photoTarget = ref(-1)
const appendRecognizing = ref(false)

function pickPhoto(idx: number) {
  photoTarget.value = idx
  photoRef.value?.click()
}

/** 线下模式：拍题目页 → 识别 → 追加一道草稿题（第一行还是空题时直接填第一行） */
function pickPhotoAppend() {
  photoTarget.value = -2
  photoRef.value?.click()
}

async function onPhotoChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    error.value = '题目照片格式不对，请上传 jpg / png / webp 格式的图片。'
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    error.value = '题目照片太大了（超过 10MB），请压缩后再试。'
    return
  }
  const appendMode = photoTarget.value === -2
  let q: QuestionForm
  if (appendMode) {
    appendRecognizing.value = true
    const first = questions.value[0]
    const firstBlank =
      questions.value.length === 1 && first && !first.prompt.trim() && !first.knowledge_point.trim()
    q = firstBlank ? first : blankQuestion()
    if (!firstBlank) questions.value.push(q)
  } else {
    const found = questions.value[photoTarget.value]
    if (!found) return
    q = found
  }
  q.recognizing = true
  error.value = ''
  try {
    const res = await teacher.recognizePhoto(file)
    if (res.question_text) q.prompt = res.question_text
    if (res.steps?.length) q.standard_steps_text = res.steps.join('\n')
    q.recognized = true
  } catch (err: unknown) {
    error.value = '照片识别失败：' + errMsg(err, '请稍后重试。')
    console.error(err)
  } finally {
    q.recognizing = false
    appendRecognizing.value = false
  }
}

async function submit() {
  error.value = ''
  if (!title.value.trim()) {
    error.value = '请填写作业标题。'
    return
  }
  if (mode.value === 'offline') {
    if (!workbookId.value) {
      error.value = '线下作业要先选一本练习册（知识库是空的就先上传整本 PDF）。'
      return
    }
    if (!pageRange.value.trim()) {
      error.value = '请填写页码 / 题号范围，学生才知道做练习册的哪一部分。'
      return
    }
  }
  const valid = questions.value.filter((q) => q.prompt.trim() || q.knowledge_point.trim())
  if (!valid.length) {
    error.value = '至少填写 1 道题目。'
    return
  }
  for (let i = 0; i < valid.length; i++) {
    if (!valid[i].prompt.trim() || !valid[i].knowledge_point.trim()) {
      error.value = `第 ${i + 1} 题的题干和知识点都要填写。`
      return
    }
  }
  // 评分系统：总分合法性 + 分值占比合计必须 = 100%（容差 0.5），否则拦截发布
  const total = Number(totalScore.value)
  if (!total || Number.isNaN(total) || total <= 0) {
    error.value = '请填写有效的作业总分（满分）。'
    return
  }
  if (!weightSumOk.value) {
    error.value = weightSum.value < 100
      ? `分值占比合计是 ${fmtScore(weightSum.value)}%，还差 ${fmtScore(100 - weightSum.value)}%，请调整各题占比或点「一键均分」后再发布。`
      : `分值占比合计是 ${fmtScore(weightSum.value)}%，超出了 ${fmtScore(weightSum.value - 100)}%，请调整各题占比或点「一键均分」后再发布。`
    return
  }
  // 发布前批量验算参考答案（v0.9.3）：填了答案的题全部验一遍；
  // suspect 只在题下留黄色标记并弹一次确认，教师确认后照常发布，绝不拦截
  const withAnswer = valid.filter((q) => q.reference_answer.trim())
  if (withAnswer.length) {
    checkingAll.value = true
    try {
      await Promise.all(withAnswer.map((q) => runCheck(q)))
    } catch (e) {
      console.error(e) // runCheck 内部已兜底，这里只防万一：验算出问题不挡发布
    } finally {
      checkingAll.value = false
    }
    const suspects = withAnswer.filter((q) => q.check_status === 'suspect')
    if (suspects.length) {
      const nums = suspects.map((q) => questions.value.indexOf(q) + 1).join('、')
      const go = window.confirm(
        `有 ${suspects.length} 道题的参考答案可能有误（第 ${nums} 题），验算说明已标在对应题目下方。\n` +
        'AI 验算只是提醒，确认仍要发布吗？'
      )
      if (!go) return
    }
  }
  const payload: TeacherAssignmentInput = {
    title: title.value.trim(),
    subject: subject.value,
    total_score: total,
    questions: valid.map((q) => ({
      type: 'math' as const,
      prompt: q.prompt.trim(),
      knowledge_point: q.knowledge_point.trim(),
      standard_steps: q.standard_steps_text.split('\n').map((s) => s.trim()).filter(Boolean),
      reference_answer: q.reference_answer.trim() || undefined,
      // 评分系统：填了占比才下发；留空的题后端按题数均分
      weight_pct: q.weight_pct === null || q.weight_pct === undefined || Number.isNaN(Number(q.weight_pct))
        ? undefined
        : Number(q.weight_pct)
    }))
  }
  // 空数组的 standard_steps 不下发，保持请求干净
  payload.questions.forEach((q) => {
    if (!q.standard_steps?.length) delete q.standard_steps
  })
  if (mode.value === 'offline') {
    payload.mode = 'offline'
    payload.workbook_id = Number(workbookId.value)
    payload.page_range = pageRange.value.trim()
    if (deadline.value) payload.deadline = deadline.value.length === 16 ? `${deadline.value}:00` : deadline.value
  }
  submitting.value = true
  try {
    await teacher.createAssignment(payload)
    ok.value = true
    setTimeout(() => router.push('/teacher/assignments'), 600)
  } catch (e: unknown) {
    error.value = '发布失败：' + errMsg(e, '请稍后重试。')
    console.error(e)
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await loadWorkbooks()
  // 带 mode 的链接直达第二级表单（v0.12.0）：书架跳入 ?mode=offline&workbook_id=<id>、
  // 第一级选方式时写入的 ?mode= 刷新后都停在表单级
  if (route.query.mode === 'offline' || route.query.mode === 'online') {
    mode.value = route.query.mode
    step.value = 'form'
    const wid = Number(route.query.workbook_id)
    if (wid && workbooks.value.some((w) => w.id === wid)) {
      workbookId.value = wid
    }
  }
})
</script>

<style scoped>
/* ---------- 两级导航（v0.12.0） ---------- */
.choose-grid { max-width: 880px; margin: 0 auto; }
.choose-grid .mode-card { padding: 26px 24px; gap: 8px; }
.mode-enter { display: inline-flex; align-items: center; gap: 6px; margin-top: 10px; font-size: 13.5px; font-weight: 700; color: var(--primary); }
.choose-hint { text-align: center; color: var(--text-3); font-size: 13px; margin-top: 16px; }
.form-topbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
.back-btn { padding-left: 4px; font-weight: 600; }
.mode-chip {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 13px; font-weight: 600; color: var(--primary);
  background: var(--primary-50); border: 1px solid #D9E1F2;
  padding: 6px 13px; border-radius: 999px;
}
/* ---------- 表单布局：按实际位置并排，不再逐行堆叠 ---------- */
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.grid-q-meta { display: grid; grid-template-columns: 1fr 330px; gap: 14px; margin-bottom: 14px; }
.grid-q-body { display: grid; grid-template-columns: 1.5fr 1fr; gap: 14px; }
.grid-2 .form-row, .grid-q-meta .form-row, .grid-q-body .form-row { margin-bottom: 0; }
@media (max-width: 760px) {
  .grid-2, .grid-q-meta, .grid-q-body { grid-template-columns: 1fr; }
}
/* ---------- 输入控件统一样式（全局裸样式太素，含 number/datetime 的补齐） ---------- */
.publish-page input[type='text'], .publish-page input[type='number'],
.publish-page input[type='datetime-local'], .publish-page textarea, .publish-page select {
  border: 1.5px solid #D9E1F2; border-radius: 10px; background: #FBFCFF;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}
.publish-page input[type='number'], .publish-page input[type='datetime-local'] {
  width: 100%; padding: 10px 12px; font-size: 14px; font-family: inherit; color: var(--text);
}
.publish-page input:focus, .publish-page textarea:focus, .publish-page select:focus {
  background: #fff; border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-50); outline: none;
}
.publish-page select:disabled { background: #F1F4F9; color: var(--text-3); cursor: not-allowed; }
.publish-page .score-input { width: 110px; }
/* ---------- 底部吸底操作条 ---------- */
.publish-actions {
  position: sticky; bottom: 14px; z-index: 5;
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  background: var(--card); border: 1px solid #E4E9F2; border-radius: 14px;
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.14); padding: 12px 14px; margin-bottom: 16px;
}
.publish-actions .spacer { flex: 1; }
.weight-mini { font-size: 13px; color: var(--text-2); }
.weight-mini b { color: var(--green); }
.weight-mini.bad b { color: var(--red); }
.q-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; gap: 10px; flex-wrap: wrap; }
.q-actions { display: flex; gap: 8px; align-items: center; }
.mode-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.mode-card {
  display: flex; flex-direction: column; align-items: flex-start; gap: 6px;
  text-align: left; cursor: pointer; font-family: var(--font); color: var(--text);
  background: #fff; border: 2px solid #E4E9F2; border-radius: 14px; padding: 18px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}
.mode-card:hover { transform: translateY(-1px); box-shadow: var(--shadow); }
.mode-card.active { border-color: var(--primary); background: var(--primary-50); }
.mode-icon {
  width: 42px; height: 42px; border-radius: 12px;
  background: var(--primary-50); color: var(--primary);
  display: flex; align-items: center; justify-content: center;
}
.mode-card.active .mode-icon { background: var(--primary); color: #fff; }
.mode-name { font-size: 16px; font-weight: 700; }
.mode-desc { font-size: 13px; color: var(--text-2); line-height: 1.55; }
.wb-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.wb-row select { flex: 1 1 220px; width: auto; }
.wb-row a.btn { text-decoration: none; }
/* 练习册封面缩略图条（v0.6.0） */
.wb-strip { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
.wb-thumb {
  width: 76px; padding: 6px 6px 5px; cursor: pointer; font-family: var(--font); color: var(--text);
  background: #fff; border: 2px solid #E4E9F2; border-radius: 10px;
  display: flex; flex-direction: column; align-items: center; gap: 5px;
  transition: border-color 0.2s ease, transform 0.2s ease;
}
.wb-thumb:hover { transform: translateY(-1px); }
.wb-thumb.active { border-color: var(--primary); background: var(--primary-50); }
.wb-thumb img { width: 44px; height: 59px; object-fit: cover; border-radius: 2px 4px 4px 2px; box-shadow: 0 3px 7px rgba(15, 23, 42, 0.2); }
.wb-thumb-spine {
  width: 44px; height: 59px; border-radius: 2px 4px 4px 2px;
  background: var(--primary-50); color: var(--primary);
  display: flex; align-items: center; justify-content: center;
}
.wb-thumb-name {
  font-size: 11px; line-height: 1.3; max-width: 64px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.btn.danger-outline { background: #fff; color: var(--red); border: 1px solid #FECACA; }
.btn.danger-outline:hover { background: var(--red-bg); }
/* 评分系统：总分/占比输入与合计条 */
.score-input-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.score-input { width: 110px; flex: none; }
.weight-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 13px 18px; }
.weight-sum { font-size: 14px; }
.weight-sum b { color: var(--green); font-size: 16px; }
.weight-sum.bad b { color: var(--red); }
.weight-bar .hint { flex: 1; min-width: 200px; }
.weight-bar .btn { margin-left: auto; }
.offline-photo-card { border: 1px dashed #B7C9F5; background: #FBFCFF; }
/* 参考答案 AI 验算（v0.9.3） */
.answer-label-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; }
.answer-label-row label { margin-bottom: 0; }
.card.q-suspect { border: 1.5px solid var(--amber); background: #FFFBEB; }
.check-note { display: flex; align-items: flex-start; gap: 5px; font-size: 12.5px; line-height: 1.5; margin-top: 7px; }
.check-note .check-ic { flex: none; display: inline-flex; margin-top: 1px; }
.check-note.ok { color: var(--green); align-items: center; }
.check-note.ok .check-ic { margin-top: 0; }
.check-note.warn { color: #92400E; }
.check-note.muted { color: var(--text-3); }
@media (prefers-reduced-motion: reduce) {
  .mode-card { transition: none; }
}
</style>
