<!-- 教师端：发布作业（v0.2.0 新增；v0.5.0 双模式）
     发布分两种模式（v0.5.0）：
       - 线上作业：手动录题 / 逐题拍照识别，学生逐题拍照批改（原流程）。
       - 线下作业 · 练习册：从练习册知识库选一本（可现场上传整本 PDF）+ 填页码范围 + 截止时间，
         再拍照上传题目页识别成草稿题，教师检查修改后发布；学生作答方式与线上完全一致。
     契约：POST /api/teacher/assignments（4.7，v0.5.0 加 mode/workbook_id/page_range/deadline）、
           练习册知识库 4.15~4.17、拍照识别 4.9。本轮题目仍只支持数学。 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>发布作业</h2>
      <p class="page-sub">先选发布方式，再填内容。发布后学生端立即可见。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="ok" class="ok-msg">发布成功，正在跳转到作业列表…</div>

    <!-- 第一步：选模式 -->
    <div class="card">
      <h3>第一步 · 选择发布方式</h3>
      <div class="mode-grid">
        <button type="button" class="mode-card" :class="{ active: mode === 'online' }" @click="mode = 'online'">
          <span class="mode-icon"><AppIcon name="edit" :size="22" /></span>
          <span class="mode-name">线上作业</span>
          <span class="mode-desc">在这里逐题录入（或拍照识别）题目，学生在系统里逐题拍照作答、逐步批改。</span>
        </button>
        <button type="button" class="mode-card" :class="{ active: mode === 'offline' }" @click="mode = 'offline'">
          <span class="mode-icon"><AppIcon name="book" :size="22" /></span>
          <span class="mode-name">线下作业 · 练习册</span>
          <span class="mode-desc">作业来自纸质练习册：选一本练习册、写清页码，拍下题目页识别成题，学生照着练习册做、拍照提交。</span>
        </button>
      </div>
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
      <div class="form-row">
        <label>页码 / 题号范围</label>
        <input v-model="pageRange" type="text" placeholder="例如：第 12-14 页 第 1-8 题" maxlength="64" />
      </div>
      <div class="form-row" style="margin-bottom: 0">
        <label>截止时间（选填）</label>
        <input v-model="deadline" type="datetime-local" />
      </div>
    </div>

    <div class="card">
      <h3>基本信息</h3>
      <div class="form-row">
        <label>作业标题</label>
        <input v-model="title" type="text" :placeholder="mode === 'offline' ? '例如：练习册 P12-14 勾股定理练习' : '例如：第二周数学作业'" maxlength="128" />
      </div>
      <div class="form-row" style="margin-bottom: 0">
        <label>学科</label>
        <select v-model="subject" disabled>
          <option value="math">数学</option>
        </select>
        <p class="hint" style="margin-top: 6px">目前专注数学作业，支持拍照批改与逐步诊断。</p>
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

    <div v-for="(q, idx) in questions" :key="idx" class="card">
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
      <div class="form-row">
        <label>知识点</label>
        <input v-model="q.knowledge_point" type="text" placeholder="例如：一元一次方程" maxlength="64" />
      </div>
      <div class="form-row">
        <label>标准解题步骤（选填，每行一步，含第一步原式，供批改参考）</label>
        <textarea v-model="q.standard_steps_text" rows="4" placeholder="3x-5=10&#10;3x=10+5&#10;3x=15&#10;x=5"></textarea>
      </div>
      <div class="form-row" style="margin-bottom: 0">
        <label>参考答案（选填）</label>
        <input v-model="q.reference_answer" type="text" placeholder="例如：x=5" />
      </div>
    </div>

    <input ref="photoRef" type="file" accept="image/jpeg,image/png,image/webp" hidden @change="onPhotoChange" />
    <div class="toolbar">
      <button class="btn secondary inline-icon" @click="addQuestion"><AppIcon name="plus" :size="15" /> 添加一题</button>
      <button class="btn" :disabled="submitting" @click="submit">
        {{ submitting ? '发布中…' : mode === 'offline' ? '发布线下作业' : '发布作业' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
  recognized: boolean   // 是否刚通过照片识别填入（展示检查提示）
  recognizing: boolean  // 识别请求进行中
}

const mode = ref<'online' | 'offline'>('online')
const title = ref('')
const subject = ref<'math'>('math')
const blankQuestion = (): QuestionForm => ({
  prompt: '', knowledge_point: '', standard_steps_text: '', reference_answer: '',
  recognized: false, recognizing: false
})
const questions = ref<QuestionForm[]>([blankQuestion()])
const submitting = ref(false)
const error = ref('')
const ok = ref(false)

function errMsg(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof d === 'string' ? d : fallback
}

function addQuestion() {
  questions.value.push(blankQuestion())
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
  const payload: TeacherAssignmentInput = {
    title: title.value.trim(),
    subject: subject.value,
    questions: valid.map((q) => ({
      type: 'math' as const,
      prompt: q.prompt.trim(),
      knowledge_point: q.knowledge_point.trim(),
      standard_steps: q.standard_steps_text.split('\n').map((s) => s.trim()).filter(Boolean),
      reference_answer: q.reference_answer.trim() || undefined
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
  // 从「我的练习」书架跳入时预选（v0.6.0）：?mode=offline&workbook_id=<id>
  if (route.query.mode === 'offline') {
    mode.value = 'offline'
    const wid = Number(route.query.workbook_id)
    if (wid && workbooks.value.some((w) => w.id === wid)) {
      workbookId.value = wid
    }
  }
})
</script>

<style scoped>
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
.offline-photo-card { border: 1px dashed #B7C9F5; background: #FBFCFF; }
@media (prefers-reduced-motion: reduce) {
  .mode-card { transition: none; }
}
</style>
