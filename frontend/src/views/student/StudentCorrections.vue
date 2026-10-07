<!-- 学生端：订正错题
     从学习画像取错题（需要加固的知识点 + 最近错误），针对某条 error 提交订正，
     后端自动判定正误（is_correct：true/false/null）。
     v0.4.0 口径：订正成功只是「已订正」；响应带 can_verify 时引导去学习报告
     做二次验证，通过验证该知识点才算「已修复」。本地 fixedIds 仅表示已订正。 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>订正错题</h2>
      <p class="page-sub">把错过的题重新做对，知识点就真正属于你了。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载错题中…</div>

    <template v-else>
      <div class="card" v-if="errorList.length">
        <div class="form-row" style="margin-bottom: 0">
          <label>选择要订正的题目</label>
          <select v-model="selectedErrorId" @change="onSelect">
            <option v-for="e in errorList" :key="e.id" :value="e.id">
              [{{ e.knowledge_point }} · {{ e.error_type }}] {{ e.step_text }}
              {{ fixedIds.has(e.id) ? '（已订正）' : e.is_stubborn ? '（需要加固）' : '' }}
            </option>
          </select>
        </div>
      </div>

      <template v-if="selectedError">
        <div class="card">
          <h3>题目回顾</h3>
          <p class="step-text">出错的步骤：{{ selectedError.step_text }}</p>
          <p class="detail"><strong>解析：</strong>{{ sanitizeStudentCopy(selectedError.detail) }}</p>
          <p style="margin-top: 10px">
            <ErrorTypeBadge :type="selectedError.error_type" />
            <span class="badge badge-blue">{{ selectedError.knowledge_point }}</span>
            <span v-if="fixedIds.has(selectedError.id)" class="badge badge-green">已订正</span>
            <span v-else-if="selectedError.is_stubborn" class="badge badge-amber">需要加固</span>
          </p>
        </div>

        <div class="card">
          <h3>我的订正</h3>
          <div class="form-row">
            <label>写出这一步的正确内容</label>
            <input v-model="content" type="text" placeholder="例如：2x=7-3" />
          </div>
          <button class="btn" :disabled="submitting || !content.trim()" @click="submit">
            {{ submitting ? '判定中…' : '提交订正' }}
          </button>
        </div>

        <div v-if="result" class="card">
          <h3>判定结果</h3>
          <p v-if="result.is_correct === true"><span class="badge badge-green">订正成功</span></p>
          <p v-else-if="result.is_correct === false"><span class="badge badge-amber">再想一想</span></p>
          <p v-else><span class="badge badge-gray">已转交老师确认</span></p>
          <p class="note">
            {{
              result.is_correct === true
                ? '做得好，这条错题订正对了。'
                : result.is_correct === false
                  ? '这次还不太对，再看看解析，换个思路试一次。'
                  : '暂时无法自动判定，老师会帮你看一下。'
            }}
          </p>
          <p class="note hint">{{ result.note }}</p>
          <!-- v0.4.0：订正成功 → 引导二次验证（通过才算知识点已修复） -->
          <div v-if="result.can_verify" class="verify-cta">
            <p>再做对一道同类题验证一下，这个知识点就真正修复啦。</p>
            <router-link :to="verifyLink">
              <button class="btn small inline-icon"><AppIcon name="target" :size="15" /> 去验证</button>
            </router-link>
          </div>
        </div>
      </template>

      <div v-if="!errorList.length" class="card">
        <div class="empty">太棒了，目前没有需要订正的题目，去 <router-link to="/student/assignments" style="color: var(--primary)">作业列表</router-link> 继续挑战吧。</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useStudentStore } from '../../stores/student'
import { useAuthStore } from '../../stores/auth'
import type { CorrectionResult, GradingError, StudentMistake } from '../../api/types'
import { sanitizeStudentCopy } from '../../utils/errorType'
import { getFixedErrorIds, markErrorFixed } from '../../utils/correctionTracker'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import AppIcon from '../../components/icons/AppIcon.vue'

const student = useStudentStore()
const auth = useAuthStore()
const route = useRoute()

const errorList = ref<GradingError[]>([])
const selectedErrorId = ref<number | ''>('')
const content = ref('')
const result = ref<CorrectionResult | null>(null)
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const fixedIds = ref<Set<number>>(new Set())

const selectedError = computed(() => errorList.value.find((e) => e.id === selectedErrorId.value) ?? null)

/** 「去验证」深链（v0.6.0）：带知识点名跳科目详情页，详情页会直接打开验证面板
 * （当前真实报告只有数学科目；详情页内部还会按知识点所属科目自动纠偏跳转） */
const verifyLink = computed(() => {
  const kp = result.value?.knowledge_point ?? selectedError.value?.knowledge_point ?? ''
  return kp ? `/student/report/math?verify=${encodeURIComponent(kp)}` : '/student/report'
})

function onSelect() {
  content.value = ''
  result.value = null
}

async function submit() {
  if (!selectedErrorId.value) return
  submitting.value = true
  error.value = ''
  result.value = null
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
    const [currentMistakes, archivedMistakes] = await Promise.all([
      student.fetchMyMistakes(false),
      student.fetchMyMistakes(true)
    ])
    const mistakes = [...new Map([...currentMistakes, ...archivedMistakes].map((item) => [item.id, item])).values()]
    errorList.value = mistakes.map(toGradingError)
    if (auth.user) {
      const serverFixed = mistakes.filter((item) => item.latest_correction?.is_correct === true).map((item) => item.id)
      fixedIds.value = new Set([...fixedIds.value, ...serverFixed])
    }
    if (errorList.value.length) {
      const requestedId = Number(route.query.error_id)
      selectedErrorId.value = errorList.value.some((item) => item.id === requestedId)
        ? requestedId
        : errorList.value[0].id
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
.step-text { font-size: 15px; font-weight: 600; margin-bottom: 8px; }
.detail { font-size: 14px; color: var(--text-2); }
.note { margin-top: 8px; font-size: 14px; color: var(--text); }
.note.hint { color: var(--text-3); font-size: 13px; }
.verify-cta {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  background: var(--primary-50); border: 1px solid #DBEAFE; border-radius: 10px;
  padding: 11px 14px; margin-top: 12px; font-size: 14px;
}
</style>
