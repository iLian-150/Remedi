<!-- 教师端：待审核（v0.9.0 新增）——AI 批改先过老师这一关，通过后学生才看得到诊断。
     左列待审队列（按提交时间正序，先交先审），右列审核详情：完整分步诊断 +
     逐条错因（可先一键纠错改错因，再点「通过」= 改后通过）+「通过」按钮；
     通过后后端给学生发 review_approved 提醒。页顶可一键全部通过。
     接口：4.23 待审队列 / 4.24 审核详情 / 4.25 通过 / 4.26 全部通过 / 4.2 一键纠错。 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>待审核</h2>
      <p class="page-sub">AI 已经批改完的作业先在这里把关：确认无误点「通过」，学生的诊断和错题才会放行；错因分错了可以先改再通过。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="okMsg" class="ok-msg">{{ okMsg }}</div>
    <div v-if="loading" class="loading">加载待审核队列中…</div>

    <template v-else>
      <div class="card queue-head">
        <span class="queue-count">
          待审核 <b class="tnum">{{ items.length }}</b> 份
        </span>
        <button class="btn small" :disabled="!items.length || approvingAll" @click="approveAll">
          {{ approvingAll ? '处理中…' : '全部通过' }}
        </button>
      </div>

      <div v-if="!items.length" class="card">
        <div class="empty">太好了，没有待审核的提交，AI 批改的结果都已经放行给学生了。</div>
      </div>

      <div v-else class="review-grid">
        <!-- 待审队列 -->
        <div class="card queue-card">
          <button
            v-for="it in items"
            :key="it.submission_id"
            type="button"
            class="queue-row"
            :class="{ active: it.submission_id === selectedId }"
            @click="selectItem(it.submission_id)"
          >
            <span class="queue-row-main">
              <span class="queue-row-top">
                <strong>{{ it.student.name }}</strong>
                <span class="badge badge-amber">待审核</span>
                <span v-if="it.error_count" class="badge badge-red tnum">{{ it.error_count }} 处问题</span>
                <span v-else class="badge badge-green">全对</span>
              </span>
              <span class="queue-row-stem">{{ it.assignment_title }} · {{ it.question_stem }}</span>
              <span class="queue-row-meta">
                <span class="badge badge-blue">{{ it.knowledge_point }}</span>
                <span class="tnum">{{ fmtTime(it.submitted_at) }}</span>
              </span>
            </span>
            <AppIcon name="chevron-right" :size="16" class="queue-row-arrow" />
          </button>
        </div>

        <!-- 审核详情 -->
        <div class="review-detail">
          <div v-if="detailLoading" class="card"><div class="loading">加载诊断中…</div></div>
          <template v-else-if="detail">
            <div class="card">
              <h3>提交信息</h3>
              <p style="font-size: 14px">
                学生：<strong>
                  <router-link :to="`/teacher/students/${detail.student.id}`" style="color: var(--primary)">{{ detail.student.name }}</router-link>
                </strong>（学号 {{ detail.student.student_no }}）
                · 作业：{{ detail.assignment_title }}
                · 题目：{{ detail.question.stem }}
                · 提交时间：{{ fmtTime(detail.submitted_at) }}
              </p>
            </div>

            <div class="card process-card" v-if="detail.process_check?.suspicious">
              <h3 class="process-title">
                <AppIcon name="alert" :size="17" class="process-icon" />
                过程提示
              </h3>
              <p class="card-sub">供审核参考：该生最终答案正确，但作答过程存在下列情况。</p>
              <ul class="process-signals">
                <li v-for="s in detail.process_check.signals" :key="s.code">{{ s.text }}</li>
              </ul>
              <p class="hint" v-if="detail.process_check.final_answer || detail.process_check.reference_answer">
                学生最终答案：{{ detail.process_check.final_answer ?? '—' }}
                · 参考答案：{{ detail.process_check.reference_answer ?? '—' }}
              </p>
            </div>

            <div class="card">
              <h3>分步诊断</h3>
              <div
                v-for="st in detail.diagnosis.steps"
                :key="st.seq"
                class="step"
                :class="{ 'first-error': st.status === 'error', correct: st.status === 'ok' }"
              >
                <div class="step-title">{{ st.seq === 0 ? '题干' : `步骤 ${st.seq}` }} · {{ STEP_STATUS_TEXT[st.status] }}</div>
                <p>{{ st.text }}</p>
              </div>
              <p v-if="!detail.diagnosis.errors.length" class="ok-line">这份作答全部正确，通过后学生会看到鼓励反馈。</p>
            </div>

            <div class="card" v-if="detail.diagnosis.errors.length">
              <h3>错因复核</h3>
              <p class="card-sub">分类不对的先在这里改，改完点下方「通过」就是改后通过（纠错会照常回标入库；待审核期间不会提前通知学生）。</p>
              <div v-for="e in detail.diagnosis.errors" :key="e.id" class="review-error">
                <p>
                  <ErrorTypeBadge :type="e.error_type" />
                  <span class="badge badge-blue">{{ e.knowledge_point }}</span>
                  <span class="conf-text tnum">置信度 {{ Math.round(e.confidence * 100) }}%</span>
                  <span v-if="e.is_stubborn" class="badge badge-red">顽固误区</span>
                  <span v-if="e.teacher_corrected" class="badge badge-gray">已纠错</span>
                </p>
                <p class="detail-text">{{ e.detail }}</p>
                <p v-if="e.step_text" class="detail-text">出错步骤：{{ e.step_text }}</p>
                <div class="correct-row">
                  <select v-model="correctForms[e.id].type">
                    <option value="">改错因…</option>
                    <option v-for="t in ERROR_TYPES" :key="t" :value="t">{{ t }}</option>
                  </select>
                  <input v-model="correctForms[e.id].note" type="text" placeholder="备注（可选）" />
                  <button
                    class="btn small secondary"
                    :disabled="!correctForms[e.id].type || correctingId === e.id"
                    @click="saveCorrection(e.id)"
                  >
                    {{ correctingId === e.id ? '保存中…' : '保存纠错' }}
                  </button>
                </div>
              </div>
            </div>

            <div class="card" v-if="detail.score">
              <h3>AI 评分</h3>
              <p class="score-line">
                本题满分 <b class="tnum">{{ fmtScore(detail.score.question_max) }}</b> 分 ·
                AI 评分 <b class="tnum">{{ detail.score.ai_score !== null ? fmtScore(detail.score.ai_score) : '—' }}</b> 分
                <span class="hint">（按步骤对错折算：步骤对了 {{ detail.score.ok_steps }}/{{ detail.score.total_steps }} 步）</span>
              </p>
              <p v-if="detail.score.final_score !== null" class="score-line" style="margin-top: 6px">
                最终分 <b class="tnum">{{ fmtScore(detail.score.final_score) }}</b> 分（已落定）
              </p>
              <p v-else class="hint" style="margin-top: 6px">觉得 AI 分不准，可以在下方通过时改分；不改就按 AI 评分给学生。</p>
            </div>

            <div class="card approve-bar">
              <p class="hint" style="margin: 0">通过后，学生会立刻收到一条提醒，并能看到这份诊断与错题。</p>
              <div v-if="detail.review_status === 'pending' && detail.score" class="final-score-box">
                <label>最终分</label>
                <input
                  v-model="finalScoreInput"
                  type="number" min="0" :max="detail.score.question_max" step="0.5"
                  :placeholder="detail.score.ai_score !== null ? String(detail.score.ai_score) : 'AI 分'"
                />
                <span class="hint">/ {{ fmtScore(detail.score.question_max) }} 分 · 留空 = 用 AI 评分</span>
              </div>
              <button class="btn" :disabled="approving" @click="approveSelected">
                {{ approving ? '通过中…' : '通过审核' }}
              </button>
            </div>
          </template>
          <div v-else class="card">
            <div class="empty">从左边队列里选一份提交，查看它的 AI 诊断。</div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useTeacherStore } from '../../stores/teacher'
import type { ReviewDetail, ReviewPendingItem } from '../../api/types'
import { ERROR_TYPES, STEP_STATUS_TEXT } from '../../api/types'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import AppIcon from '../../components/icons/AppIcon.vue'

const teacher = useTeacherStore()
const route = useRoute()

const items = ref<ReviewPendingItem[]>([])
const selectedId = ref<number | null>(null)
const detail = ref<ReviewDetail | null>(null)
const loading = ref(false)
const detailLoading = ref(false)
const approving = ref(false)
const approvingAll = ref(false)
const correctingId = ref<number | null>(null)
const error = ref('')
const okMsg = ref('')
/** 每条错因一份纠错表单（type/note），按 error_id 索引 */
const correctForms = reactive<Record<number, { type: string; note: string }>>({})

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

function fmtScore(v: number): string {
  return String(Math.round(v * 10) / 10)
}

/** 评分系统：老师改分输入（字符串，留空 = 用 AI 评分通过） */
const finalScoreInput = ref('')

function errDetail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof d === 'string' ? d : '请稍后重试。'
}

async function loadQueue(preselect?: number) {
  loading.value = true
  error.value = ''
  try {
    items.value = await teacher.fetchPendingReviews()
    const target = items.value.find((i) => i.submission_id === preselect) ?? items.value[0]
    if (target) {
      await selectItem(target.submission_id)
    } else {
      selectedId.value = null
      detail.value = null
    }
  } catch (e) {
    error.value = '待审核队列加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function selectItem(submissionId: number) {
  selectedId.value = submissionId
  detailLoading.value = true
  detail.value = null
  finalScoreInput.value = ''
  try {
    const d = await teacher.fetchReviewDetail(submissionId)
    detail.value = d
    d.diagnosis.errors.forEach((e) => {
      if (!correctForms[e.id]) correctForms[e.id] = { type: '', note: '' }
    })
  } catch (e) {
    error.value = '审核详情加载失败：' + errDetail(e)
    console.error(e)
  } finally {
    detailLoading.value = false
  }
}

async function saveCorrection(errorId: number) {
  const form = correctForms[errorId]
  if (!form?.type) return
  correctingId.value = errorId
  error.value = ''
  try {
    await teacher.correctError(errorId, {
      error_type: form.type,
      teacher_note: form.note.trim() || undefined
    })
    form.type = ''
    form.note = ''
    okMsg.value = '错因已修改并回标入库，点「通过审核」后学生才会看到。'
    if (selectedId.value) await selectItem(selectedId.value)
  } catch (e) {
    error.value = '纠错保存失败：' + errDetail(e)
    console.error(e)
  } finally {
    correctingId.value = null
  }
}

async function approveSelected() {
  if (!selectedId.value) return
  // 评分系统：改分先做前端校验（0 ~ 本题满分），后端还会再验一遍
  let finalScore: number | undefined
  const raw = finalScoreInput.value.trim()
  if (raw !== '') {
    const v = Number(raw)
    const max = detail.value?.score?.question_max ?? 0
    if (Number.isNaN(v) || v < 0 || v > max) {
      error.value = `最终分要在 0 到 ${fmtScore(max)} 分之间。`
      return
    }
    finalScore = v
  }
  approving.value = true
  error.value = ''
  try {
    const name = detail.value?.student.name ?? ''
    await teacher.approveReview(selectedId.value, finalScore)
    items.value = items.value.filter((i) => i.submission_id !== selectedId.value)
    okMsg.value = `已通过，${name} 会收到提醒并能看到诊断了。`
    detail.value = null
    selectedId.value = null
    const next = items.value[0]
    if (next) await selectItem(next.submission_id)
  } catch (e) {
    error.value = '审核通过失败：' + errDetail(e)
    console.error(e)
  } finally {
    approving.value = false
  }
}

async function approveAll() {
  approvingAll.value = true
  error.value = ''
  try {
    const n = await teacher.approveAllReviews()
    items.value = []
    detail.value = null
    selectedId.value = null
    okMsg.value = `已全部通过 ${n} 份，学生们都会收到提醒。`
  } catch (e) {
    error.value = '全部通过失败：' + errDetail(e)
    console.error(e)
  } finally {
    approvingAll.value = false
  }
}

onMounted(() => {
  const preset = Number(route.query.submission_id)
  void loadQueue(preset || undefined)
})
</script>

<style scoped>
.queue-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 18px; }
.queue-count { font-size: 15px; font-weight: 600; }
.queue-count b { color: var(--primary); font-size: 19px; }
.review-grid { display: grid; grid-template-columns: 360px 1fr; gap: 16px; align-items: start; }
@media (max-width: 1080px) {
  .review-grid { grid-template-columns: 1fr; }
}
.queue-card { padding: 10px; display: flex; flex-direction: column; gap: 6px; }
.queue-row {
  display: flex; align-items: center; gap: 8px; text-align: left;
  background: #fff; border: 1px solid #EDF0F4; border-radius: 10px;
  padding: 11px 12px; cursor: pointer; font-family: inherit; width: 100%;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.queue-row:hover { border-color: #C9D6F2; }
.queue-row.active { border-color: var(--primary); background: var(--primary-50); }
.queue-row-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 5px; }
.queue-row-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 14px; }
.queue-row-stem {
  font-size: 13px; color: var(--text-2);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.queue-row-meta { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-3); }
.queue-row-arrow { color: var(--text-3); flex-shrink: 0; }
.review-detail > .card:last-child { margin-bottom: 0; }
.detail-text { margin-top: 8px; font-size: 14px; color: var(--text-2); }
.review-error { padding: 12px 0; border-bottom: 1px solid #F1F3F6; }
.review-error:last-child { border-bottom: none; padding-bottom: 2px; }
.correct-row { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.correct-row select { width: 150px; flex-shrink: 0; }
.correct-row input { flex: 1; min-width: 140px; width: auto; }
.approve-bar { display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.score-line { font-size: 14.5px; }
.score-line b { color: var(--primary); }
.final-score-box { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.final-score-box label { font-size: 13.5px; font-weight: 600; }
.final-score-box input { width: 96px; }
.ok-line { font-size: 14.5px; color: #065F46; margin-top: 4px; }
.process-card { border-left: 4px solid var(--amber, #D97706); background: #FFFBEB; }
.process-title { display: flex; align-items: center; gap: 7px; }
.process-icon { color: var(--amber, #D97706); flex-shrink: 0; }
.process-signals { margin: 6px 0 8px; padding-left: 20px; font-size: 14px; color: var(--text-2); }
.process-signals li { margin: 3px 0; }
</style>
