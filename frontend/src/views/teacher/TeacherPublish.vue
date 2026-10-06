<!-- 教师端：发布作业（v0.2.0 新增）
     本轮只支持数学题型：表单固定 subject=math、题目 type=math（后端接口保留 essay 字段，前端不给入口）。
     契约：POST /api/teacher/assignments（4.7） -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>发布作业</h2>
      <p class="page-sub">布置一份数学作业，发布后学生端立即可见。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="ok" class="ok-msg">发布成功，正在跳转到作业列表…</div>

    <div class="card">
      <h3>基本信息</h3>
      <div class="form-row">
        <label>作业标题</label>
        <input v-model="title" type="text" placeholder="例如：第二周数学作业" maxlength="128" />
      </div>
      <div class="form-row" style="margin-bottom: 0">
        <label>学科</label>
        <select v-model="subject" disabled>
          <option value="math">数学</option>
        </select>
        <p class="hint" style="margin-top: 6px">目前专注数学作业，支持拍照批改与逐步诊断。</p>
      </div>
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
        {{ submitting ? '发布中…' : '发布作业' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useTeacherStore } from '../../stores/teacher'
import type { TeacherAssignmentInput } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'

const teacher = useTeacherStore()
const router = useRouter()

interface QuestionForm {
  prompt: string
  knowledge_point: string
  standard_steps_text: string
  reference_answer: string
  recognized: boolean   // 是否刚通过照片识别填入（展示检查提示）
  recognizing: boolean  // 识别请求进行中
}

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

function addQuestion() {
  questions.value.push(blankQuestion())
}

// ---------- 拍照识别题目（v0.2.1）：识别结果填入当前题行，教师检查后再发布 ----------
const photoRef = ref<HTMLInputElement | null>(null)
const photoTarget = ref(-1)

function pickPhoto(idx: number) {
  photoTarget.value = idx
  photoRef.value?.click()
}

async function onPhotoChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  const q = questions.value[photoTarget.value]
  if (!file || !q) return
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    error.value = '题目照片格式不对，请上传 jpg / png / webp 格式的图片。'
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    error.value = '题目照片太大了（超过 10MB），请压缩后再试。'
    return
  }
  q.recognizing = true
  error.value = ''
  try {
    const res = await teacher.recognizePhoto(file)
    if (res.question_text) q.prompt = res.question_text
    if (res.steps?.length) q.standard_steps_text = res.steps.join('\n')
    q.recognized = true
  } catch (err: unknown) {
    const d = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = '照片识别失败：' + (typeof d === 'string' ? d : '请稍后重试。')
    console.error(err)
  } finally {
    q.recognizing = false
  }
}

async function submit() {
  error.value = ''
  if (!title.value.trim()) {
    error.value = '请填写作业标题。'
    return
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
  submitting.value = true
  try {
    await teacher.createAssignment(payload)
    ok.value = true
    setTimeout(() => router.push('/teacher/assignments'), 600)
  } catch (e: unknown) {
    const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = '发布失败：' + (typeof d === 'string' ? d : '请稍后重试。')
    console.error(e)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.q-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; gap: 10px; flex-wrap: wrap; }
.q-actions { display: flex; gap: 8px; align-items: center; }
</style>
