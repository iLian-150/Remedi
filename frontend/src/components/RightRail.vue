<!-- 右侧栏（v0.3.0 首版：便利贴 + 日历 + 当天详情；v0.3.1 改为按页面分工）：
     - mode="notes"（学生普通页，含主页对话页）：显示老师的便利贴提醒。
     - mode="mistakes"（学生错题本）：显示尚未学会的错误类别与复习入口。
     - mode="calendar"（学生/教师作业列表页）：只显示作业日历；点选日期 → 写入对应 store 的
       assignmentDateFilter，作业列表页据此筛选 + 显示当天进度；再次点同一天 = 取消筛选。
     - mode="corrections"（学生订正页，v0.9.1）：订正日历——按错题所属提交日期打点+计数；
       点选日期 → 写入 student store 的 correctionsDateFilter，订正页据此只看那天的错题；
       再次点同一天 = 取消筛选。数据走 store.fetchCorrectableMistakes 前端聚合，
       与订正页同口径（仅诊断产生的错题；待审核错题同步计入待订正）。
     - mode="timeline"（学生学习报告页：总览与科目详情，本次改造）：错题时间线——
       报告页右栏不再是信箱；面板默认收起，只露标题行（图标+「错题时间线」+条数+
       展开箭头），点开才展开纵向时间线（全局 .timeline 样式复用）；科目详情路由下
       按 question_subject 只显示本科目；点条目跳 /student/diagnosis?submission_id=。
       数据同走 store.fetchCorrectableMistakes（源头是 /student/mistakes 响应，
       只读复用，不新造接口）。
     收起/展开由 App.vue 控制（收起态 FAB 图标随场景变：notes=邮件、mistakes=错题本、calendar/corrections=日历）。
     通知唯一来源：教师在教师端一键纠错 → 后端落库 → 这里 GET 拉取展示，学生端不本地伪造。 -->
<template>
  <div class="rail-inner">
    <div class="rail-head">
      <span class="rail-title">
        <AppIcon :name="mode === 'notes' ? 'megaphone' : mode === 'mistakes' ? 'book' : mode === 'timeline' ? 'history' : 'calendar'" :size="17" />
        {{ mode === 'notes' ? '提醒' : mode === 'mistakes' ? '错题复习' : mode === 'corrections' ? '订正日历' : mode === 'timeline' ? '错题时间线' : '日历' }}
      </span>
      <button class="icon-btn" title="收起右侧栏" @click="$emit('close')">
        <AppIcon name="chevron-right" :size="17" />
      </button>
    </div>

    <!-- 便利贴提醒（仅学生） -->
    <template v-if="mode === 'notes'">
      <div class="rail-sec-head">
        <h3>老师的消息</h3>
        <span v-if="unread > 0" class="badge badge-red">{{ unread }} 条未读</span>
        <button v-if="notes.length && unread > 0" class="text-btn" @click="markAllRead">全部标已读</button>
      </div>
      <div v-if="notes.length" class="notes">
        <div
          v-for="(n, i) in notes"
          :key="n.id"
          class="note-wrap"
          :style="{ '--i': i }"
        >
          <div
            class="note"
            :class="[`note-c${i % 3}`, { read: n.is_read }]"
            :style="{ '--tilt': `${i % 2 === 0 ? -1 : 1}deg`, animationDelay: `${-i * 0.9}s` }"
            @click="openNote(n)"
          >
            <span class="note-tape"></span>
            <p class="note-content">{{ n.content }}</p>
            <span class="note-time">{{ fmtTime(n.created_at) }}</span>
            <span v-if="!n.is_read" class="note-dot" title="未读"></span>
          </div>
        </div>
      </div>
      <p v-else class="hint" style="margin-bottom: 6px">暂无新提醒</p>
    </template>

    <!-- 错题本专属复习清单：待复习数按尚未学会的错误类别计算。 -->
    <template v-else-if="mode === 'mistakes'">
      <div class="review-overview">
        <span class="review-overview-icon"><AppIcon name="history" :size="17" /></span>
        <div><strong>{{ reviewCategories.length ? `还有 ${reviewCategories.length} 类待巩固` : '复习进度' }}</strong><span>已学会 {{ reviewStudiedCount }} / {{ reviewTotalCount }} 类错误</span></div>
      </div>
      <div class="rail-sec-head review-sec-head">
        <h3>优先复习</h3>
        <span v-if="reviewCategories.length" class="badge badge-blue">{{ reviewCategories.length }} 类待学</span>
      </div>
      <div v-if="reviewLoading" class="loading" style="padding: 18px 0">正在整理待复习错题…</div>
      <div v-else-if="reviewError" class="review-empty" role="alert">
        <strong>待复习内容加载失败</strong>
        <p>暂时无法读取错题本，请重试。</p>
        <button type="button" @click="loadMistakeReview">重新加载</button>
      </div>
      <div v-else-if="reviewCategories.length" class="review-list">
        <article v-for="item in reviewCategories.slice(0, 5)" :key="item.key" class="review-card">
          <div class="review-card-heading">
            <span class="review-subject">{{ reviewSubjectName(item.subject) }}</span>
            <span class="review-error-count">{{ item.items.length }} 道相关错题</span>
          </div>
          <h4>{{ item.knowledgePoint || item.categoryLabel }}</h4>
          <p class="review-card-meta">{{ item.assignmentTitle }} · {{ item.categoryLabel }}</p>
          <button type="button" class="review-start" @click="beginReview(item.mistakeId)">开始复习<AppIcon name="arrow-right" :size="13" /></button>
        </article>
        <button type="button" class="review-all-link" @click="router.push('/student/mistakes')">查看错题本<AppIcon name="arrow-right" :size="12" /></button>
      </div>
      <div v-else class="review-empty">
        <span class="review-empty-icon"><AppIcon name="check" :size="19" /></span>
        <strong>{{ reviewRaw.length ? '目前没有待巩固类别' : '错题本还没有记录' }}</strong>
        <p>{{ reviewRaw.length ? '所有错误类别都已标记学会，继续保持。' : '完成作业诊断后，错题和复习进度会显示在这里。' }}</p>
        <button type="button" @click="router.push('/student/mistakes')">查看错题本<AppIcon name="arrow-right" :size="12" /></button>
      </div>
    </template>

    <!-- 错题时间线（仅学习报告页）：默认收起只露标题行，点开才展开纵向时间线 -->
    <template v-else-if="mode === 'timeline'">
      <button type="button" class="tl-toggle" @click="toggleTimeline">
        <span class="tl-toggle-main">
          <AppIcon name="history" :size="16" />
          <span>{{ tlScopeLabel }} · 共 <span class="tnum">{{ tlCount ?? '…' }}</span> 条</span>
        </span>
        <span class="tl-chevron" :class="{ open: tlExpanded }"><AppIcon name="chevron-down" :size="16" /></span>
      </button>
      <div v-if="tlExpanded" class="tl-body">
        <div v-if="tlLoading" class="loading" style="padding: 18px 0">加载错题时间线…</div>
        <p v-else-if="!timelineItems.length" class="hint" style="padding: 6px 0">还没有错题记录，继续保持。</p>
        <div v-else class="timeline tl-list">
          <div
            v-for="item in timelineItems"
            :key="item.id"
            class="timeline-item tl-item"
            @click="gotoSubmission(item.submission_id)"
          >
            <span :class="item.corrected ? 'timeline-dot green' : errorTypeDotClass(item.error_type)"></span>
            <div class="timeline-time">{{ fmtTime(item.created_at) }}</div>
            <div class="timeline-body">
              <p class="tl-stem">{{ item.question_stem }}</p>
              <p class="tl-meta">
                <span class="badge badge-blue">{{ item.knowledge_point }}</span>
                <ErrorTypeBadge :type="item.error_type as ErrorType" />
                <span v-if="item.corrected" class="badge badge-green">已订正</span>
                <span v-else class="badge badge-gray">未订正</span>
              </p>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 日历（作业列表页=作业日历；订正页=订正日历）：选中日期与对应页面筛选共用 store 状态 -->
    <template v-else>
      <AssignmentCalendar :marks="mode === 'corrections' ? correctionMarks : marks" :selected="dateFilter" @select="onSelectDay" />
      <p class="hint" style="margin-top: 10px">
        {{ calendarHint }}
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useStudentStore } from '../stores/student'
import { useTeacherStore } from '../stores/teacher'
import type { ErrorType, NotificationItem, StudentMistake } from '../api/types'
import { errorTypeDotClass } from '../utils/errorType'
import AppIcon from './icons/AppIcon.vue'
import AssignmentCalendar from './AssignmentCalendar.vue'
import ErrorTypeBadge from './ErrorTypeBadge.vue'

const props = defineProps<{
  /** notes：便利贴提醒；mistakes：错题本待复习清单；calendar：作业日历（与作业列表筛选联动）；
   * corrections：订正日历（v0.9.1，与订正页筛选联动）；
   * timeline：错题时间线（学习报告页，默认收起，点开才展开） */
  mode: 'notes' | 'mistakes' | 'calendar' | 'corrections' | 'timeline'
}>()

// v0.8.2：未读数改由 student store 持有（fetchNotifications / markNotificationsRead 内部回写），
// 本组件不再 emit unread-change；FAB 角标与本栏的未读徽标读同一份 store 状态。
const emit = defineEmits<{
  (e: 'close'): void
}>()

const auth = useAuthStore()
const student = useStudentStore()
const teacher = useTeacherStore()
const router = useRouter()
const route = useRoute()

const isStudent = computed(() => auth.user?.role === 'student')

/** 日历选中日期 = 对应 store 的筛选值（单一事实来源，日历与页面双向同步）；
 * 订正日历只归学生，走 correctionsDateFilter；作业日历按当前角色分流 */
const dateFilter = computed(() =>
  props.mode === 'corrections'
    ? student.correctionsDateFilter
    : isStudent.value
      ? student.assignmentDateFilter
      : teacher.assignmentDateFilter
)

/** 日历下方提示文案：随模式与选中态变化 */
const calendarHint = computed(() => {
  if (props.mode === 'corrections') {
    return dateFilter.value
      ? '已按所选日期筛选订正列表，点「查看全部」或再点一次该日期可恢复全部。'
      : '圆点是哪天交的作业里出了错题，点一天就只看那天的。'
  }
  return dateFilter.value
    ? '已按所选日期筛选作业列表，点「返回查看全部作业」或再点一次该日期可恢复全部。'
    : '点任意一天，只看当天发布的作业。'
})

const notes = ref<NotificationItem[]>([])
const unread = ref(0)
/** 作业日历标记：yyyy-mm-dd → 当天发布的作业份数（仅作业发布，不含提交） */
const marks = ref<Record<string, number>>({})
/** 订正日历标记（v0.9.1）：yyyy-mm-dd → 当天提交里产生的可订正错题条数 */
const correctionMarks = ref<Record<string, number>>({})

/** 错题时间线（报告页）：原始错题（诊断产生，源头 /student/mistakes）与展开态（默认收起） */
const tlRaw = ref<StudentMistake[]>([])
const tlLoading = ref(false)
const tlExpanded = ref(false)
const tlCount = ref<number | null>(null)
const tlLoaded = ref(false)
let tlLoadPromise: Promise<void> | null = null

interface ReviewCategory {
  key: string
  subject: string
  categoryLabel: string
  knowledgePoint: string
  assignmentTitle: string
  mistakeId: number
  items: StudentMistake[]
  priority: number
  createdAt: string
  studied: boolean
}
const reviewRaw = ref<StudentMistake[]>([])
const reviewLoading = ref(false)
const reviewError = ref(false)
const reviewSummary = computed(() => {
  const groups = new Map<string, ReviewCategory>()
  for (const item of reviewRaw.value) {
    if (item.source_kind === 'student_saved') continue
    const key = `${item.assignment_id}:${item.category_key}`
    const existing = groups.get(key)
    if (existing) {
      existing.items.push(item)
      existing.studied = existing.studied && item.category_studied
      existing.priority += item.similar_occurrences.length + Number(item.is_stubborn)
      if (item.created_at < existing.createdAt) existing.createdAt = item.created_at
      continue
    }
    groups.set(key, {
      key,
      subject: item.question_subject,
      categoryLabel: item.category_label || item.error_type,
      knowledgePoint: item.knowledge_point,
      assignmentTitle: item.assignment_title,
      mistakeId: item.id,
      items: [item],
      priority: item.similar_occurrences.length + Number(item.is_stubborn),
      createdAt: item.created_at,
      studied: item.category_studied
    })
  }
  return {
    totalCount: groups.size,
    categories: Array.from(groups.values())
      .filter((item) => !item.studied)
      .sort((left, right) => right.priority - left.priority || left.createdAt.localeCompare(right.createdAt))
  }
})
const reviewTotalCount = computed(() => reviewSummary.value.totalCount)
const reviewCategories = computed<ReviewCategory[]>(() => reviewSummary.value.categories)
const reviewStudiedCount = computed(() => reviewTotalCount.value - reviewCategories.value.length)

const TL_SUBJECT_TEXT: Record<string, string> = {
  math: '数学', english: '英语', english_exercise: '英语练习', physics: '物理', chemistry: '化学',
  chinese: '语文', biology: '生物', history: '历史', geography: '地理', politics: '道德与法治',
  computer_science: '信息科技'
}
/** 科目详情路由带 subject 参数时只看该科目；总览页为空 = 全部 */
const tlSubject = computed(() =>
  typeof route.params.subject === 'string' ? route.params.subject : ''
)
const tlScopeLabel = computed(() =>
  tlSubject.value ? `${TL_SUBJECT_TEXT[tlSubject.value] ?? tlSubject.value}错题` : '全部错题'
)
/** 时间线条目：按科目过滤 → 按错题产生时间倒序 → 附已订正标记（最新一次订正判对） */
const timelineItems = computed(() => {
  const items: Array<StudentMistake & { corrected: boolean }> = []
  for (const item of tlRaw.value) {
    if (tlSubject.value && item.question_subject !== tlSubject.value) continue
    items.push({ ...item, corrected: item.latest_correction?.is_correct === true })
  }
  return items.sort((a, b) => b.created_at.localeCompare(a.created_at))
})

watch(tlSubject, () => {
  if (props.mode !== 'timeline') return
  if (tlLoaded.value) {
    tlCount.value = timelineItems.value.length
  } else if (!tlExpanded.value) {
    void loadTimelineCount()
  }
})

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

function onSelectDay(date: string) {
  // 再点一次已选中的日期 = 取消筛选
  const next = date === dateFilter.value ? '' : date
  if (props.mode === 'corrections') student.setCorrectionsDateFilter(next)
  else if (isStudent.value) student.setAssignmentDateFilter(next)
  else teacher.setAssignmentDateFilter(next)
}

async function loadNotes() {
  try {
    const res = await student.fetchNotifications()
    notes.value = res.items
    unread.value = res.unread_count
  } catch (e) {
    console.error(e)
    // 进入提醒场景时 App 复用了列表响应中的未读数；列表失败则退回轻量计数接口。
    void student.refreshUnread()
  }
}

async function loadMarks() {
  try {
    const m: Record<string, number> = {}
    if (isStudent.value) {
      // 与学生作业列表页共用轻量提交状态请求；日历只需要发布时间。
      const list = await student.fetchAssignments(false, true)
      for (const a of list) {
        const d = a.created_at.slice(0, 10)
        if (d) m[d] = (m[d] ?? 0) + 1
      }
    } else {
      const list = await teacher.fetchTeacherAssignments()
      for (const a of list) {
        const d = a.created_at.slice(0, 10)
        if (d) m[d] = (m[d] ?? 0) + 1
      }
    }
    marks.value = m
  } catch (e) {
    console.error(e)
  }
}

/** 订正日历标记（v0.9.1）：拉可订正错题，按所属提交日期聚合（与订正页同口径：
 * submitted_at 优先，缺失时用错题产生时间兜底） */
async function loadCorrectionMarks() {
  try {
    const list = await student.fetchCorrectableMistakes()
    const m: Record<string, number> = {}
    for (const item of list) {
      const d = (item.submitted_at ?? item.created_at).slice(0, 10)
      if (d) m[d] = (m[d] ?? 0) + 1
    }
    correctionMarks.value = m
  } catch (e) {
    console.error(e)
  }
}

async function loadTimelineCount() {
  const subject = tlSubject.value
  tlCount.value = null
  try {
    const count = await student.fetchMistakeCount(subject || undefined)
    if (props.mode === 'timeline' && tlSubject.value === subject && !tlLoaded.value) {
      tlCount.value = count
    }
  } catch (e) {
    console.error(e)
  }
}

/** 错题时间线仅在展开时加载完整错题本数据；折叠标题使用轻量计数接口。 */
async function loadTimeline() {
  if (tlLoaded.value) {
    tlCount.value = timelineItems.value.length
    return
  }
  if (tlLoadPromise) return tlLoadPromise

  tlLoading.value = true
  const request = (async () => {
    try {
      tlRaw.value = await student.fetchCorrectableMistakes()
      tlLoaded.value = true
      tlCount.value = timelineItems.value.length
    } catch (e) {
      console.error(e)
    } finally {
      tlLoading.value = false
      tlLoadPromise = null
    }
  })()
  tlLoadPromise = request
  return request
}

function toggleTimeline() {
  tlExpanded.value = !tlExpanded.value
  if (tlExpanded.value) void loadTimeline()
}

function reviewSubjectName(value: string) {
  return TL_SUBJECT_TEXT[value] ?? (value || '其他学科')
}

async function loadMistakeReview() {
  reviewLoading.value = true
  reviewError.value = false
  try {
    reviewRaw.value = await student.fetchMyMistakes(false)
    student.mistakeReviewCount = reviewCategories.value.length
  } catch (e) {
    reviewRaw.value = []
    student.mistakeReviewCount = 0
    reviewError.value = true
    console.error(e)
  } finally {
    reviewLoading.value = false
  }
}

function beginReview(mistakeId: number) {
  emit('close')
  void router.push({ path: '/student/mistakes', query: { review: String(mistakeId) } })
}

function onMistakeReviewChanged() {
  if (props.mode === 'mistakes') void loadMistakeReview()
}

async function loadForMode() {
  if (!auth.user) return
  if (props.mode === 'notes') {
    if (isStudent.value) await loadNotes()
  } else if (props.mode === 'mistakes') {
    await loadMistakeReview()
  } else if (props.mode === 'corrections') {
    await loadCorrectionMarks()
  } else if (props.mode === 'timeline') {
    tlLoaded.value = false
    if (tlExpanded.value) await loadTimeline()
    else await loadTimelineCount()
  } else {
    await loadMarks()
  }
}

// 模式随路由切换（学生主页↔作业列表等），切回来时重新拉数据保证新鲜
watch(() => props.mode, loadForMode)

// 教师在作业列表页发布/删除作业后，日历标记同步刷新
function onAssignmentsChanged() {
  if (props.mode === 'calendar') void loadMarks()
}

onMounted(() => {
  void loadForMode()
  window.addEventListener('assignments-changed', onAssignmentsChanged)
  window.addEventListener('mistake-review-changed', onMistakeReviewChanged)
})
onUnmounted(() => {
  window.removeEventListener('assignments-changed', onAssignmentsChanged)
  window.removeEventListener('mistake-review-changed', onMistakeReviewChanged)
})

function gotoSubmission(id: number) {
  router.push(`/student/diagnosis?submission_id=${id}`)
}

async function openNote(n: NotificationItem) {
  if (!n.is_read) {
    try {
      const res = await student.markNotificationsRead([n.id])
      n.is_read = true
      unread.value = res.unread_count
    } catch (e) {
      console.error(e)
    }
  }
  if (n.related_submission_id) gotoSubmission(n.related_submission_id)
}

async function markAllRead() {
  try {
    const res = await student.markNotificationsRead()
    notes.value.forEach((n) => (n.is_read = true))
    unread.value = res.unread_count
  } catch (e) {
    console.error(e)
  }
}
</script>

<style scoped>
.rail-head {
  display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px;
}
.rail-title { display: inline-flex; align-items: center; gap: 7px; font-size: 15.5px; font-weight: 700; }
.rail-sec-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.rail-sec-head h3 { font-size: 14.5px; }

/* ---------- 错题时间线（报告页模式） ---------- */
.tl-toggle {
  width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 8px;
  background: var(--primary-50); border: 1px solid #DBEAFE; border-radius: 10px;
  padding: 10px 12px; cursor: pointer; font-family: var(--font);
  font-size: 13.5px; font-weight: 600; color: var(--text);
  transition: border-color 0.2s ease, background 0.2s ease;
}
.tl-toggle:hover { border-color: var(--primary); }
.tl-toggle-main { display: inline-flex; align-items: center; gap: 7px; min-width: 0; }
.tl-chevron { display: inline-flex; flex-shrink: 0; color: var(--text-3); transition: transform 0.25s ease; }
.tl-chevron.open { transform: rotate(180deg); }
.tl-body { margin-top: 14px; }
.tl-list { margin-top: 2px; }
.tl-item { cursor: pointer; }
.tl-item:hover .tl-stem { color: var(--primary); }
.tl-stem {
  font-weight: 600; font-size: 13.5px; line-height: 1.45;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.tl-meta { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 5px; }

/* ---------- 错题本复习清单 ---------- */
.review-overview {
  display: flex; align-items: center; gap: 10px; padding: 12px;
  border: 1px solid #DBEAFE; border-radius: 12px; background: linear-gradient(135deg, #EFF6FF, #F8FAFF);
}
.review-overview-icon, .review-empty-icon {
  width: 34px; height: 34px; flex: 0 0 auto; display: inline-flex; align-items: center; justify-content: center;
  border-radius: 10px; background: #fff; color: var(--primary); box-shadow: 0 1px 3px rgba(15, 23, 42, .08);
}
.review-overview strong, .review-overview span { display: block; }
.review-overview strong { font-size: 13.5px; }
.review-overview div > span { margin-top: 3px; color: var(--text-3); font-size: 11.5px; line-height: 1.4; }
.review-sec-head { margin: 17px 0 10px; }
.review-list { display: flex; flex-direction: column; gap: 10px; }
.review-card { padding: 12px; border: 1px solid var(--border); border-radius: 12px; background: #fff; box-shadow: 0 2px 6px rgba(15, 23, 42, .04); }
.review-card-heading { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.review-subject { padding: 3px 7px; border-radius: 6px; background: var(--primary-50); color: var(--primary); font-size: 11.5px; font-weight: 700; }
.review-error-count { color: var(--text-3); font-size: 11px; white-space: nowrap; }
.review-card h4 { margin-top: 9px; font-size: 14px; line-height: 1.4; }
.review-card-meta { margin-top: 4px; color: var(--text-3); font-size: 11.5px; line-height: 1.45; }
.review-start, .review-empty button, .review-all-link {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px; cursor: pointer; font-family: var(--font); font-weight: 600;
}
.review-start { width: 100%; margin-top: 11px; padding: 8px 10px; border: 1px solid #DBEAFE; border-radius: 8px; background: var(--primary-50); color: var(--primary); font-size: 12px; }
.review-start:hover { border-color: var(--primary); background: #E5EEFF; }
.review-all-link { width: 100%; padding: 7px; border: 0; background: transparent; color: var(--primary); font-size: 12px; }
.review-all-link:hover { text-decoration: underline; }
.review-empty { display: flex; flex-direction: column; align-items: center; padding: 24px 12px; text-align: center; }
.review-empty-icon { margin-bottom: 10px; color: #0F9F7A; background: #EAFBF4; }
.review-empty strong { font-size: 13.5px; }
.review-empty p { margin-top: 5px; color: var(--text-3); font-size: 12px; line-height: 1.55; }
.review-empty button { margin-top: 12px; padding: 7px 10px; border: 1px solid var(--border); border-radius: 8px; background: #fff; color: var(--primary); font-size: 12px; }
@media (prefers-reduced-motion: reduce) {
  .tl-chevron { transition: none; }
}
.text-btn {
  margin-left: auto; background: none; border: none; cursor: pointer;
  color: var(--primary); font-size: 12.5px; font-family: var(--font);
}
.text-btn:hover { text-decoration: underline; }

/* ---------- 便利贴 ---------- */
.notes { display: flex; flex-direction: column; gap: 14px; padding-top: 8px; }
.note-wrap { animation: note-in 0.45s cubic-bezier(0.34, 1.4, 0.64, 1) both; animation-delay: calc(var(--i) * 60ms); }
@keyframes note-in {
  from { opacity: 0; transform: translateY(-16px); }
  to { opacity: 1; transform: translateY(0); }
}
.note {
  position: relative; cursor: pointer; border-radius: 4px 4px 10px 4px;
  padding: 16px 13px 10px; box-shadow: 0 3px 8px rgba(15, 23, 42, 0.13);
  transform: rotate(var(--tilt));
  animation: note-sway 6.2s ease-in-out infinite;
  transition: box-shadow 0.25s ease;
}
.note-c0 { background: #fff3b8; }
.note-c1 { background: #ffdce8; }
.note-c2 { background: #d6e9ff; }
.note.read { filter: saturate(0.45); opacity: 0.72; }
.note:hover {
  animation: none;
  transform: rotate(0deg) scale(1.03);
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.2);
}
@keyframes note-sway {
  0%, 100% { transform: rotate(calc(var(--tilt) - 0.6deg)); }
  50% { transform: rotate(calc(var(--tilt) + 0.6deg)); }
}
.note-tape {
  position: absolute; top: -9px; left: 50%;
  transform: translateX(-50%) rotate(-2deg);
  width: 62px; height: 17px; border-radius: 2px;
  background: rgba(255, 255, 255, 0.55);
  border-left: 1px dashed rgba(0, 0, 0, 0.07);
  border-right: 1px dashed rgba(0, 0, 0, 0.07);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}
.note-content { font-size: 13.5px; line-height: 1.55; color: #3f3a2a; }
.note-time { display: block; margin-top: 6px; font-size: 11.5px; color: rgba(63, 58, 42, 0.6); }
.note-dot {
  position: absolute; top: 8px; right: 8px; width: 8px; height: 8px;
  border-radius: 50%; background: var(--red);
}

@media (prefers-reduced-motion: reduce) {
  .note-wrap { animation: none; }
  .note { animation: none; }
  .note:hover { transform: rotate(var(--tilt)); }
}
</style>
