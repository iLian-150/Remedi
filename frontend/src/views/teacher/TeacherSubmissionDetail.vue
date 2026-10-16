<!-- 教师端：诊断详情
     说明：契约 4.1 的 error 对象本身携带完整诊断信息（学生/题目/出错步骤/错因/置信度/顽固标记），
     因此 :id 按 error_id 解释，从错误列表接口取详情并在此做一键纠错。
     完整作答步骤链契约未提供（学生侧 3.5 仅学生本人可看），此处不展示。 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>诊断详情</h2>
      <p class="page-sub">AI 诊断的完整信息；分类存疑时可一键纠错。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-if="item">
      <div class="card">
        <h3>提交信息</h3>
        <p style="font-size: 14px">
          学生：<strong>
            <router-link :to="`/teacher/students/${item.student.id}`" style="color: var(--primary)">{{ item.student.name }}</router-link>
          </strong>（学号 {{ item.student.student_no }}）
          · 题目：{{ item.question.stem }}
          · 时间：{{ fmtTime(item.created_at) }}
        </p>
      </div>

      <div class="card">
        <h3>关联作答步骤</h3>
        <div class="step first-error">
          <div class="step-title">
            {{ item.step_seq == null ? '未关联具体步骤' : `步骤 ${item.step_seq} · 首次出错` }}
          </div>
          <p v-if="item.step_text">{{ item.step_text }}</p>
          <p v-else class="hint">暂无作答步骤文本。</p>
        </div>
        <p class="hint">注：完整作答步骤链契约未对教师端提供，以上为出错步骤本身。</p>
      </div>

      <div class="card">
        <h3>错因标签 <span class="hint" style="font-weight: 400">（疑似分类，供教师参考）</span></h3>
        <p>
          <ErrorTypeBadge :type="item.error_type" />
          <span class="conf-text tnum">置信度 {{ Math.round(item.confidence * 100) }}%</span>
          <span v-if="item.is_stubborn" class="badge badge-red">顽固误区</span>
          <span v-else class="badge badge-green">偶发失误</span>
          <span class="badge badge-blue">知识点：{{ item.knowledge_point }}</span>
        </p>
        <div class="conf-bar"><div :style="{ width: `${Math.round(item.confidence * 100)}%` }"></div></div>
        <p v-if="item.detail" class="detail">{{ item.detail }}</p>
        <p v-else class="hint">暂无诊断说明。</p>
        <p v-if="item.teacher_corrected" class="corrected-note">
          已纠错（{{ item.teacher_note || '无备注' }}）
        </p>
      </div>

      <!-- 一键纠错表单：修正错因类型 + 备注 -->
      <div class="card">
        <h3>一键纠错</h3>
        <p class="hint">如果 AI 的错因分类有误，在此修正并备注。修正会回标入库，用于后续模型优化。</p>
        <div class="form-row">
          <label>修正后的错因类型</label>
          <select v-model="correctType">
            <option value="">请选择…</option>
            <option v-for="t in ERROR_TYPES" :key="t" :value="t">{{ t }}</option>
          </select>
        </div>
        <div class="form-row">
          <label>备注</label>
          <textarea v-model="correctNote" rows="3" placeholder="补充说明（可选）"></textarea>
        </div>
        <div v-if="correctMsg" :class="correctOk ? 'ok-msg' : 'error-msg'">{{ correctMsg }}</div>
        <button class="btn" :disabled="correcting || !correctType" @click="submitCorrection">
          {{ correcting ? '提交中…' : '提交纠错' }}
        </button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useTeacherStore } from '../../stores/teacher'
import type { TeacherErrorItem } from '../../api/types'
import { ERROR_TYPES } from '../../api/types'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'

const route = useRoute()
const teacher = useTeacherStore()

const item = ref<TeacherErrorItem | null>(null)
const loading = ref(false)
const error = ref('')

const correctType = ref('')
const correctNote = ref('')
const correcting = ref(false)
const correctMsg = ref('')
const correctOk = ref(false)

function fmtTime(t: string): string {
  return t.replace('T', ' ')
}

async function submitCorrection() {
  correcting.value = true
  correctMsg.value = ''
  try {
    const updated = await teacher.correctError(Number(route.params.id), {
      error_type: correctType.value,
      teacher_note: correctNote.value.trim() || undefined
    })
    if (item.value) {
      item.value.error_type = updated.error_type
      item.value.teacher_corrected = updated.teacher_corrected
      item.value.teacher_note = updated.teacher_note
    }
    correctOk.value = true
    correctMsg.value = `已修改，并通知了学生${item.value?.student.name ?? ''}（学生端会收到一条提醒便利贴）。回标数据已入库。`
    correctType.value = ''
    correctNote.value = ''
  } catch (e) {
    correctOk.value = false
    correctMsg.value = '纠错提交失败：' + errDetail(e)
    console.error(e)
  } finally {
    correcting.value = false
  }
}

function errDetail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof d === 'string' ? d : '请稍后重试。'
}

onMounted(async () => {
  loading.value = true
  try {
    const errorId = Number(route.params.id)
    if (!Number.isSafeInteger(errorId) || errorId <= 0) {
      error.value = '诊断记录编号无效。'
      return
    }
    const res = await teacher.fetchErrors({ error_id: errorId, limit: 1 })
    const found = res.items[0]
    if (found) {
      item.value = found
    } else {
      error.value = '未找到该诊断记录。'
    }
  } catch (e) {
    error.value = '诊断详情加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.hint { color: #8a94a3; font-size: 13px; margin-bottom: 12px; margin-top: 8px; }
.conf-text { font-size: 13px; color: #5f6b7a; margin-left: 8px; }
.detail { margin-top: 10px; font-size: 14px; color: #3d4650; }
.corrected-note { margin-top: 10px; font-size: 13px; color: #b07d1b; }
.ok-msg { color: #1e7e34; background: #e6f4ea; padding: 10px 14px; border-radius: 8px; margin-bottom: 12px; font-size: 14px; }
</style>
