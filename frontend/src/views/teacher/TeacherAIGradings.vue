<template>
  <div class="page ai-grading-page">
    <div class="page-head">
      <h2>AI 批改</h2>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="success" class="ok-msg">{{ success }}</div>

    <section class="card grading-toolbar">
      <label class="search-field">
        <span>搜索</span>
        <input
          v-model="keyword"
          type="text"
          placeholder="学生、作业、题目或知识点"
          @keydown.enter="load(0)"
        />
      </label>
      <button class="btn small" :disabled="loading" @click="load(0)">查询</button>
      <span class="toolbar-total">共 {{ total }} 份 AI 批改</span>
    </section>

    <form class="card threshold-settings" @submit.prevent="saveThreshold">
      <label for="grading-threshold">低分标记线</label>
      <span>低于</span>
      <input id="grading-threshold" v-model="thresholdInput" type="number" min="0" max="100" step="1" required :disabled="savingThreshold || !thresholdLoaded" />
      <span>%</span>
      <button class="btn small secondary" type="submit" :disabled="savingThreshold || !thresholdLoaded">{{ savingThreshold ? '保存中…' : '保存' }}</button>
      <span class="threshold-note">按整份作业的 AI 得分率标记；教师审核规则不变。</span>
    </form>

    <section class="card grading-list">
      <div v-if="loading" class="loading">加载中…</div>
      <div v-else-if="!items.length" class="empty">暂无 AI 批改记录。</div>
      <div v-else class="table-scroll">
        <table class="table">
          <thead>
            <tr>
              <th>学生 / 作业</th>
              <th>题目</th>
              <th>AI 得分</th>
              <th>整份作业</th>
              <th>批改状态</th>
              <th>时间</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in items"
              :key="item.submission_id"
              class="grading-row"
              :class="{ 'low-score-row': item.is_low_score }"
              @click="openDetail(item.submission_id)"
            >
              <td>
                <strong>{{ item.student.name }}</strong>
                <span class="table-sub">{{ item.assignment_title || '未命名作业' }}</span>
              </td>
              <td class="question-cell">
                <span>{{ item.question_stem || '暂无题目文本' }}</span>
                <small>{{ item.knowledge_point || item.subject }}</small>
              </td>
              <td class="score-cell tnum">
                <strong>{{ fmtScore(item.ai_score) }}</strong><span> / {{ fmtScore(item.question_max) }}</span>
                <small v-if="item.final_score !== null">教师定分 {{ fmtScore(item.final_score) }}</small>
              </td>
              <td>
                <span v-if="item.assignment_complete" class="assignment-score tnum">
                  {{ fmtScore(item.assignment_ai_score) }} / {{ fmtScore(item.assignment_max_score) }}
                </span>
                <span v-else class="table-sub">进行中</span>
                <span v-if="item.is_low_score" class="badge badge-red low-score-badge">低于 {{ threshold }}%</span>
              </td>
              <td>
                <span v-if="item.review_status === 'pending'" class="badge badge-amber">待二次批改</span>
                <span v-else-if="item.teacher_regraded" class="badge badge-blue">教师已二次批改</span>
                <span v-else class="badge badge-green">AI 已批改</span>
                <span v-if="item.error_count" class="error-count">{{ item.error_count }} 处错因</span>
                <span v-else class="table-sub">全对</span>
              </td>
              <td class="time-cell tnum">{{ fmtTime(item.submitted_at) }}</td>
              <td><button type="button" class="btn small secondary" @click.stop="openDetail(item.submission_id)">查看 / 修改</button></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="total > pageSize" class="pagination">
        <button class="btn small secondary" :disabled="offset === 0 || loading" @click="load(offset - pageSize)">上一页</button>
        <span class="tnum">{{ offset + 1 }}–{{ Math.min(offset + items.length, total) }} / {{ total }}</span>
        <button class="btn small secondary" :disabled="offset + pageSize >= total || loading" @click="load(offset + pageSize)">下一页</button>
      </div>
    </section>

    <div v-if="modalOpen" class="detail-mask" @click.self="closeDetail">
      <section class="detail-modal" role="dialog" aria-modal="true" aria-labelledby="detail-title">
        <header class="detail-header">
          <div>
            <h3 id="detail-title">AI 批改详情</h3>
            <p v-if="detail">{{ detail.assignment_title }} · {{ detail.student.name }} · {{ fmtTime(detail.submitted_at) }}</p>
          </div>
          <button class="detail-close" aria-label="关闭详情" @click="closeDetail">×</button>
        </header>

        <div v-if="detailLoading" class="detail-loading loading">加载诊断中…</div>
        <div v-else-if="detail" class="detail-body">
          <div class="detail-image">
            <a v-if="selectedItem?.image_url" :href="imageSrc(selectedItem.image_url)" target="_blank" rel="noopener noreferrer">
              <img :src="imageSrc(selectedItem.image_url)" :alt="selectedItem.image_name || '学生作答原图'" />
            </a>
            <div v-else class="image-empty">暂无作答原图</div>
          </div>

          <div class="detail-content">
            <section class="detail-panel">
              <div class="panel-title"><h4>题目</h4><span>{{ detail.question.knowledge_point || detail.question.subject }}</span></div>
              <p class="question-text">{{ detail.question.stem }}</p>
            </section>

            <section class="detail-panel">
              <div class="panel-title"><h4>解题过程</h4><span>{{ answerSteps.length }} 步</span></div>
              <div v-if="detail.process_check?.suspicious" class="process-note">
                <strong>过程提示</strong>
                <p v-for="signal in detail.process_check.signals" :key="signal.code">{{ signal.text }}</p>
                <small v-if="detail.process_check.final_answer || detail.process_check.reference_answer">
                  学生答案：{{ detail.process_check.final_answer ?? '—' }} · 参考答案：{{ detail.process_check.reference_answer ?? '—' }}
                </small>
              </div>
              <article v-for="step in answerSteps" :key="step.seq" class="answer-step" :class="{ wrong: step.status === 'error', right: step.status === 'ok' }">
                <div><strong>第 {{ step.seq }} 步</strong><span>{{ STEP_STATUS_TEXT[step.status] }}</span></div>
                <p>{{ step.text }}</p>
              </article>
              <p v-if="!answerSteps.length" class="table-sub">没有可展示的分步作答。</p>
            </section>

            <section v-if="detail.diagnosis.errors.length" class="detail-panel">
              <div class="panel-title"><h4>AI 错因</h4><span>{{ detail.diagnosis.errors.length }} 处</span></div>
              <article v-for="issue in detail.diagnosis.errors" :key="issue.id" class="issue-card">
                <div class="issue-meta">
                  <span>第 {{ issue.step_seq ?? '—' }} 步</span>
                  <ErrorTypeBadge :type="issue.error_type" />
                  <span class="conf-text tnum">置信度 {{ Math.round(issue.confidence * 100) }}%</span>
                </div>
                <p>{{ issue.detail || '暂无诊断说明。' }}</p>
                <p v-if="issue.step_text" class="table-sub">作答：{{ issue.step_text }}</p>
                <div class="correction-controls">
                  <label class="sr-only" :for="`error-type-${issue.id}`">修改错因分类</label>
                  <select :id="`error-type-${issue.id}`" v-model="correctionForms[issue.id].type">
                    <option value="">修改错因…</option>
                    <option v-for="type in ERROR_TYPES" :key="type" :value="type">{{ type }}</option>
                  </select>
                  <input v-model="correctionForms[issue.id].note" type="text" aria-label="纠错备注" placeholder="备注（可选）" />
                  <button class="btn small secondary" :disabled="!correctionForms[issue.id].type || correctingId === issue.id" @click="saveCorrection(issue.id)">
                    {{ correctingId === issue.id ? '保存中…' : '保存错因' }}
                  </button>
                </div>
              </article>
            </section>
            <section v-else class="detail-panel all-correct"><AppIcon name="check" :size="18" /> 这份作答没有识别到错因</section>

            <section v-if="detail.score" class="detail-panel score-editor">
              <div class="panel-title"><h4>教师二次批改</h4><span>本题满分 {{ fmtScore(detail.score.question_max) }} 分</span></div>
              <p class="ai-score-line">AI 评分 <strong class="tnum">{{ fmtScore(detail.score.ai_score) }}</strong> 分 · {{ detail.score.ok_steps }}/{{ detail.score.total_steps }} 步正确</p>
              <label for="regrade-score">教师确认分数</label>
              <div class="score-input-row">
                <input id="regrade-score" v-model="finalScoreInput" type="text" inputmode="decimal" />
                <span>分</span>
                <button type="button" class="chip-btn" @click="finalScoreInput = fmtScore(detail.score?.ai_score ?? null)">恢复 AI 分</button>
                <button type="button" class="chip-btn" @click="finalScoreInput = fmtScore(detail.score?.question_max ?? null)">满分</button>
              </div>
              <p v-if="detail.score.final_score !== null" class="table-sub">上次教师定分：{{ fmtScore(detail.score.final_score) }} 分</p>
              <button class="btn save-regrade" :disabled="savingRegrade" @click="saveRegrade">
                {{ savingRegrade ? '保存中…' : '保存二次批改' }}
              </button>
            </section>
          </div>
        </div>
        <div v-else class="detail-loading error-msg">{{ error || '详情加载失败。' }}</div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { useTeacherStore } from '../../stores/teacher'
import type { ReviewDetail, TeacherAIGradingItem } from '../../api/types'
import { ERROR_TYPES, STEP_STATUS_TEXT } from '../../api/types'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import AppIcon from '../../components/icons/AppIcon.vue'

const teacher = useTeacherStore()
const route = useRoute()
const pageSize = 50
const items = ref<TeacherAIGradingItem[]>([])
const total = ref(0)
const offset = ref(0)
const keyword = ref('')
const loading = ref(false)
const detailLoading = ref(false)
const modalOpen = ref(false)
const error = ref('')
const success = ref('')
const detail = ref<ReviewDetail | null>(null)
const selectedId = ref<number | null>(null)
const finalScoreInput = ref('')
const savingRegrade = ref(false)
const threshold = ref(60)
const thresholdInput = ref('60')
const thresholdLoaded = ref(false)
const savingThreshold = ref(false)
const correctingId = ref<number | null>(null)
const correctionForms = reactive<Record<number, { type: string; note: string }>>({})
let listRequest = 0
let detailRequest = 0

const selectedItem = computed(() => items.value.find((item) => item.submission_id === selectedId.value) ?? null)
const answerSteps = computed(() => detail.value?.diagnosis.steps.filter((step) => step.status !== 'stem') ?? [])

function fmtScore(score: number | null): string {
  return score === null ? '—' : String(Math.round(score * 10) / 10)
}
function fmtTime(value: string): string { return value.replace('T', ' ').slice(0, 16) }
function imageSrc(path: string): string {
  if (/^https?:\/\//i.test(path)) return path
  const base = String(import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
  return `${base}${path.startsWith('/') ? path : `/${path}`}`
}
function errDetail(value: unknown): string {
  const message = (value as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof message === 'string' ? message : '请稍后重试。'
}

async function load(newOffset = offset.value, submissionId?: number) {
  const request = ++listRequest
  offset.value = newOffset
  loading.value = true
  error.value = ''
  try {
    const page = await teacher.fetchAIGradings({
      limit: pageSize,
      offset: newOffset,
      keyword: keyword.value.trim() || undefined,
      submission_id: submissionId
    })
    if (request !== listRequest) return
    items.value = page.items
    total.value = page.total
    threshold.value = page.low_score_threshold
    if (!thresholdLoaded.value) {
      thresholdInput.value = String(page.low_score_threshold)
      thresholdLoaded.value = true
    }
    return true
  } catch (cause) {
    if (request !== listRequest) return
    error.value = `AI 批改列表加载失败：${errDetail(cause)}`
    return false
  } finally {
    if (request === listRequest) loading.value = false
  }
}

async function saveThreshold() {
  const raw = String(thresholdInput.value).trim()
  const value = Number(raw)
  if (!raw || !Number.isInteger(value) || value < 0 || value > 100) {
    error.value = '低分标记线请输入 0 到 100 之间的整数。'
    return
  }
  savingThreshold.value = true
  error.value = ''
  success.value = ''
  try {
    await teacher.updateGradingThreshold(value)
    thresholdInput.value = String(value)
    if (await load(offset.value)) success.value = '低分标记线已保存。'
    else error.value = '低分标记线已保存，列表刷新失败，请重新查询。'
  } catch (cause) {
    error.value = `低分标记线保存失败：${errDetail(cause)}`
  } finally {
    savingThreshold.value = false
  }
}

async function openDetail(submissionId: number) {
  const request = ++detailRequest
  selectedId.value = submissionId
  modalOpen.value = true
  detailLoading.value = true
  detail.value = null
  error.value = ''
  try {
    const result = await teacher.fetchReviewDetail(submissionId)
    if (request !== detailRequest || selectedId.value !== submissionId) return
    detail.value = result
    const current = items.value.find((item) => item.submission_id === submissionId)
    finalScoreInput.value = fmtScore(result.score?.final_score ?? result.score?.ai_score ?? null)
    result.diagnosis.errors.forEach((issue) => {
      if (!correctionForms[issue.id]) correctionForms[issue.id] = { type: '', note: '' }
    })
    if (!current) void load(0, submissionId)
  } catch (cause) {
    if (request === detailRequest) error.value = `详情加载失败：${errDetail(cause)}`
  } finally {
    if (request === detailRequest) detailLoading.value = false
  }
}

function closeDetail() {
  detailRequest += 1
  modalOpen.value = false
  detail.value = null
  selectedId.value = null
}
function onKeydown(event: KeyboardEvent) { if (event.key === 'Escape' && modalOpen.value) closeDetail() }

async function saveCorrection(errorId: number) {
  const form = correctionForms[errorId]
  if (!form?.type || !selectedId.value) return
  correctingId.value = errorId
  error.value = ''
  try {
    await teacher.correctError(errorId, {
      error_type: form.type,
      teacher_note: form.note.trim() || undefined
    })
    form.type = ''
    form.note = ''
    success.value = '错因已更新。'
    await openDetail(selectedId.value)
    await load(offset.value)
  } catch (cause) {
    error.value = `错因保存失败：${errDetail(cause)}`
  } finally {
    correctingId.value = null
  }
}

async function saveRegrade() {
  if (!selectedId.value || !detail.value?.score) return
  const raw = String(finalScoreInput.value ?? '').trim()
  const score = Number(raw)
  const max = detail.value.score.question_max
  if (!raw || !Number.isFinite(score) || score < 0 || score > max) {
    error.value = `分数需在 0 到 ${fmtScore(max)} 分之间。`
    return
  }
  savingRegrade.value = true
  error.value = ''
  try {
    await teacher.regradeAIGrading(selectedId.value, score)
    success.value = '二次批改已保存，学生已收到成绩更新提醒。'
    await load(offset.value)
    await openDetail(selectedId.value)
  } catch (cause) {
    error.value = `二次批改保存失败：${errDetail(cause)}`
  } finally {
    savingRegrade.value = false
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  const preset = Number(route.query.submission_id)
  void load(0, Number.isFinite(preset) && preset > 0 ? preset : undefined)
  if (Number.isFinite(preset) && preset > 0) void openDetail(preset)
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.grading-toolbar { display: flex; align-items: end; gap: 12px; flex-wrap: wrap; }
.search-field { display: grid; gap: 5px; width: min(460px, 100%); color: var(--text-2); font-size: 13px; }
.search-field input { width: 100%; }
.toolbar-total { margin-left: auto; color: var(--text-2); font-size: 13px; }
.threshold-settings { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.threshold-settings label { font-weight: 600; }
.threshold-settings input { width: 76px; }
.threshold-note { color: var(--text-2); font-size: 13px; }
.grading-list { padding: 0; overflow: hidden; }
.table-scroll { overflow-x: auto; }
.table { min-width: 980px; }
.grading-row { cursor: pointer; }
.grading-row td { vertical-align: top !important; }
.grading-row:hover td { background: var(--primary-50); }
.low-score-row td { background: #FFF7F7; }
.low-score-row:hover td { background: #FEECEC; }
.table-sub { display: block; margin-top: 4px; color: var(--text-3); font-size: 12px; }
.question-cell { max-width: 330px; }
.question-cell > span { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.question-cell small { display: block; margin-top: 4px; color: var(--text-3); }
.score-cell { white-space: nowrap; }
.score-cell strong { font-size: 16px; }
.score-cell > span { color: var(--text-3); }
.score-cell small { display: block; margin-top: 3px; color: var(--primary); }
.assignment-score { display: block; white-space: nowrap; }
.low-score-badge { margin-top: 4px; }
.error-count { display: block; margin-top: 5px; color: var(--red); font-size: 12px; }
.time-cell { white-space: nowrap; color: var(--text-2); font-size: 13px; }
.pagination { display: flex; justify-content: center; align-items: center; gap: 14px; padding: 16px; color: var(--text-2); font-size: 13px; }
.detail-mask { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: 18px; background: rgba(15, 23, 42, .48); }
.detail-modal { display: flex; flex-direction: column; width: min(1180px, 100%); max-height: min(92vh, 1000px); overflow: hidden; background: var(--bg); border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--shadow-lg); }
.detail-header { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 17px 22px; background: var(--card); border-bottom: 1px solid var(--border); }
.detail-header h3 { font-size: 18px; }
.detail-header p { margin-top: 2px; color: var(--text-2); font-size: 13px; }
.detail-close { width: 36px; height: 36px; border: 1px solid var(--border); border-radius: 9px; background: var(--card); color: var(--text-2); font-size: 24px; line-height: 1; cursor: pointer; }
.detail-body { display: grid; grid-template-columns: minmax(260px, .8fr) minmax(0, 1.2fr); gap: 16px; min-height: 0; padding: 16px; overflow: hidden; }
.detail-image { position: sticky; top: 0; align-self: start; min-height: 220px; max-height: calc(92vh - 100px); overflow: auto; background: var(--card); border: 1px solid var(--border); border-radius: 12px; }
.detail-image img { display: block; width: 100%; max-height: calc(92vh - 100px); object-fit: contain; }
.image-empty { display: grid; min-height: 220px; place-items: center; color: var(--text-3); font-size: 13px; }
.detail-content { display: flex; flex-direction: column; gap: 12px; min-width: 0; min-height: 0; overflow: auto; padding-right: 4px; }
.detail-panel { padding: 16px; background: var(--card); border: 1px solid var(--border); border-radius: 12px; }
.panel-title { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.panel-title h4 { font-size: 16px; }
.panel-title > span { color: var(--text-3); font-size: 12px; }
.question-text { white-space: pre-wrap; line-height: 1.8; overflow-wrap: anywhere; }
.answer-step { margin-top: 9px; padding: 11px 13px; border: 1px solid var(--border); border-left: 4px solid #D1D5DB; border-radius: 8px; }
.answer-step > div { display: flex; justify-content: space-between; color: var(--text-2); font-size: 12px; }
.answer-step p { margin-top: 5px; white-space: pre-wrap; overflow-wrap: anywhere; }
.answer-step.wrong { border-left-color: var(--red); background: #FFFBFB; }
.answer-step.right { border-left-color: var(--green); }
.process-note { margin-bottom: 12px; padding: 12px; background: var(--amber-bg); border-radius: 8px; color: #92400E; }
.process-note p { margin-top: 4px; }
.process-note small { display: block; margin-top: 5px; }
.issue-card { padding: 12px 0; border-top: 1px solid var(--border); }
.issue-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; color: var(--text-2); font-size: 12px; }
.issue-card > p { margin-top: 7px; white-space: pre-wrap; overflow-wrap: anywhere; }
.correction-controls { display: grid; grid-template-columns: 150px minmax(140px, 1fr) auto; gap: 8px; margin-top: 10px; }
.correction-controls select, .correction-controls input { width: 100%; min-width: 0; }
.all-correct { display: flex; align-items: center; gap: 8px; color: var(--green); }
.score-editor { border-color: #C7D2FE; }
.ai-score-line { margin-bottom: 13px; color: var(--text-2); font-size: 13px; }
.ai-score-line strong { color: var(--primary); font-size: 18px; }
.score-editor > label { display: block; margin-bottom: 5px; color: var(--text-2); font-size: 13px; }
.score-input-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.score-input-row > input { width: 130px; font-size: 18px; font-weight: 700; }
.score-input-row > span { color: var(--text-2); }
.chip-btn { padding: 6px 10px; border: 1px solid var(--border); border-radius: 999px; background: #fff; color: var(--text-2); font-size: 12px; cursor: pointer; }
.chip-btn:hover { color: var(--primary); border-color: var(--primary); }
.save-regrade { margin-top: 13px; }
.detail-loading { padding: 40px; text-align: center; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
@media (max-width: 820px) {
  .page { padding: 16px; }
  .detail-mask { padding: 7px; }
  .detail-modal { max-height: 96vh; }
  .detail-body { display: flex; flex-direction: column; overflow: auto; }
  .detail-image { position: static; max-height: 32vh; flex: none; }
  .detail-image img { max-height: 32vh; }
  .detail-content { overflow: visible; }
}
@media (max-width: 540px) {
  .toolbar-total { width: 100%; margin-left: 0; }
  .correction-controls { grid-template-columns: 1fr; }
  .detail-header { padding: 13px 15px; }
}
</style>
