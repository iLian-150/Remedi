<!-- 学生端：诊断详情（单次提交的分步诊断）
     数学：分步诊断（首次出错步骤高亮）、错因三色徽标、鼓励性文案。
     支持 ?submission_id= 预选某次提交（学习报告的错题时间线从这里跳进来）。
     文案伦理：学生端不出现「顽固误区」「疑似」「置信度」等术语。 -->
<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>诊断详情</h2>
        <p class="page-sub">查看这次作答的分步诊断与错因。</p>
      </div>
      <router-link class="btn secondary small" to="/student/mistakes">返回错题本</router-link>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>

    <div class="card" v-if="submissions.length">
      <div class="form-row" style="margin-bottom: 0">
        <label>选择一次提交</label>
        <select v-model="selectedSubmissionId" @change="loadMathDetail">
          <option v-for="s in submissions" :key="s.id" :value="s.id">
            {{ s.question_stem }} · {{ s.review_status === 'pending' ? '待老师审核' : s.error_count ? `发现 ${s.error_count} 个问题` : '全部正确' }} · {{ fmtTime(s.submitted_at) }}
          </option>
        </select>
      </div>
    </div>

    <div v-if="mathLoading" class="loading">加载批改结果中…</div>

    <!-- v0.9.0：待老师审核——诊断还没放行，只显示状态卡 -->
    <div v-if="mathDetail && mathDetail.status === 'pending_review'" class="card">
      <div class="review-pending-box">
        <span class="review-pending-icon"><AppIcon name="history" :size="17" /></span>
        <div>
          <p class="review-pending-title">这份作业已提交，正在等老师审核</p>
          <p class="review-pending-sub">老师审核通过后你会收到提醒，到时再来这里看分步诊断；有错题也会自动进错题本。</p>
        </div>
      </div>
    </div>

    <template v-if="mathDetail && mathDetail.status !== 'pending_review'">
      <div class="card">
        <h3>分步解析 <span class="badge badge-blue">{{ SUBMISSION_STATUS_TEXT[mathDetail.status] ?? mathDetail.status }}</span></h3>
        <div
          v-for="st in mathDetail.steps"
          :key="st.seq"
          class="step"
          :class="{ 'first-error': st.status === 'error', correct: st.status === 'ok' }"
        >
          <div class="step-title">
            {{ st.seq === 0 ? '题干' : `步骤 ${st.seq}` }} · {{ STEP_STATUS_TEXT[st.status] }}
          </div>
          <p>{{ st.text }}</p>
        </div>
      </div>

      <div class="card" v-if="mathDetail.errors.length">
        <h3>发现的问题</h3>
        <p class="card-sub">别灰心，看清楚问题就是进步的开始。</p>
        <div v-for="e in mathDetail.errors" :key="e.id" class="error-item">
          <p>
            <ErrorTypeBadge :type="e.error_type" />
            <span class="badge badge-blue">{{ e.knowledge_point }}</span>
            <span v-if="e.is_stubborn" class="badge badge-amber">需要加固的知识点</span>
            <span v-else class="badge badge-green">已注意，继续保持</span>
          </p>
          <p class="encourage">
            {{ e.is_stubborn ? '这个知识点还需要再加固一下，多练几道同类题会有帮助。' : '这是一次偶发的小失误，下次细心一点就好。' }}
          </p>
          <p class="detail"><strong>解析：</strong>{{ sanitizeStudentCopy(e.detail) }}</p>
          <div class="toolbar" style="margin-top: 8px; margin-bottom: 0">
            <router-link :to="{ path: '/student/corrections', query: { error_id: e.id } }"><button class="btn small secondary">去订正这道题</button></router-link>
          </div>
        </div>
        <!-- 追问（v0.4.0）：订正之前先想一想 -->
        <div v-if="mathDetail.follow_up_question" class="followup-box">
          <span class="followup-icon"><AppIcon name="lightbulb" :size="15" /></span>
          <p><b>想一想：</b>{{ mathDetail.follow_up_question }}</p>
        </div>
      </div>
      <div class="card" v-else>
        <div class="empty">这次全对，继续保持！</div>
      </div>
    </template>

    <div v-if="!mathLoading && !submissions.length" class="card">
      <div class="empty">还没有作答记录，去 <router-link to="/student/assignments" style="color: var(--primary)">作业列表</router-link> 开始第一份作业吧。</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useStudentStore } from '../../stores/student'
import type { SubmissionResult, SubmissionSummary } from '../../api/types'
import { STEP_STATUS_TEXT, SUBMISSION_STATUS_TEXT } from '../../api/types'
import { sanitizeStudentCopy } from '../../utils/errorType'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import AppIcon from '../../components/icons/AppIcon.vue'

const student = useStudentStore()
const route = useRoute()

const error = ref('')
const submissions = ref<SubmissionSummary[]>([])
const selectedSubmissionId = ref<number | ''>('')
const mathDetail = ref<SubmissionResult | null>(null)
const mathLoading = ref(false)

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

async function loadMathDetail() {
  if (!selectedSubmissionId.value) return
  mathLoading.value = true
  mathDetail.value = null
  try {
    mathDetail.value = await student.fetchSubmissionDetail(Number(selectedSubmissionId.value))
  } catch (e) {
    error.value = '批改结果加载失败。'
    console.error(e)
  } finally {
    mathLoading.value = false
  }
}

onMounted(async () => {
  try {
    submissions.value = await student.fetchMySubmissions()
    // 学习报告时间线跳入时带 ?submission_id=，优先预选该次提交
    const preset = Number(route.query.submission_id)
    const target = submissions.value.find((s) => s.id === preset) ?? submissions.value[0]
    if (target) {
      selectedSubmissionId.value = target.id
      await loadMathDetail()
    }
  } catch (e) {
    error.value = '提交记录加载失败，请确认后端已启动。'
    console.error(e)
  }
})
</script>

<style scoped>
.review-pending-box { display: flex; gap: 11px; align-items: flex-start; background: var(--amber-bg); border: 1px solid #FDE68A; border-radius: 10px; padding: 13px 15px; }
.review-pending-icon { width: 30px; height: 30px; border-radius: 50%; flex-shrink: 0; background: #fff; color: var(--amber); display: flex; align-items: center; justify-content: center; }
.review-pending-title { font-size: 14.5px; font-weight: 700; color: #92400E; }
.review-pending-sub { font-size: 13px; color: #92400E; opacity: 0.85; margin-top: 2px; }
.error-item { margin-bottom: 16px; padding-bottom: 14px; border-bottom: 1px solid #F1F3F6; }
.error-item:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
.encourage { margin-top: 8px; font-size: 14px; color: var(--text); }
.detail { margin-top: 6px; font-size: 14px; color: var(--text-2); }
.followup-box {
  display: flex; gap: 9px; align-items: flex-start;
  background: var(--primary-50); border: 1px solid #DBEAFE; border-radius: 10px;
  padding: 11px 14px; margin-top: 4px; font-size: 14px;
}
.followup-icon {
  width: 25px; height: 25px; border-radius: 50%; flex-shrink: 0;
  background: var(--primary); color: #fff;
  display: flex; align-items: center; justify-content: center;
}
.followup-box p { padding-top: 2px; }
</style>
