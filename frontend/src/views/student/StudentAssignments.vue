<!-- 学生端：作业列表 —— 交作业的统一入口
     数据源：GET /api/student/assignments（契约 3.1，含整份作业暂存进度）
     v0.2.1 曾在页内放作业日历；v0.3.0 日历迁至右侧栏；v0.3.1 日历只在本页右栏出现，
     点选日期 → store.assignmentDateFilter 生效 → 服务端按发布日期筛选并显示当天完成进度，
     「返回查看全部作业」清掉筛选。卡片按钮按作业模式分文案（v0.9.2：线上作业=
     「在线作答」、线下练习册=「拍照批改」），均进入 /student/submit?assignment_id=
     v0.9.3 试卷化：列表区整张做成「钉好的试卷」——纸面+订书钉+装订线+试卷头，
     每份作业展示为一个条目，状态改用印章（已完成=红章、待审核=琥珀章、
     未开始/进行中=灰色铅笔描边章）；入场时试卷落下、印章逐个盖下（仅首次加载，
     日期筛选切换只做轻翻页过渡不再重复盖章）。
     v0.9.3 修复：「返回查看全部作业」原先只是筛选条里的一个低调小按钮、排在提示条
     下面，用户找不到；已移到试卷头右侧、改主色醒目按钮（仅筛选生效时出现），
     筛选条只保留当天的进度信息。 -->
<template>
  <div class="page">
    <div v-if="error" class="error-msg">{{ error }}</div>

    <!-- 试卷纸面 -->
    <div class="paper">
      <div class="staple" aria-hidden="true"></div>
      <span class="binding-word" aria-hidden="true">装订线</span>

      <div class="paper-head">
        <span class="paper-head-left"></span>
        <h3 class="paper-title">我的作业</h3>
        <div class="paper-head-right">
          <span v-if="!loading" class="paper-count tnum">共 {{ assignments.length }} 份</span>
          <!-- 筛选生效时：试卷头右侧的主色按钮，一眼可见、随时清筛选 -->
          <button v-if="dateFilter" class="btn filter-clear-btn" @click="clearFilter">
            <AppIcon name="chevron-left" :size="15" />返回查看全部作业
          </button>
        </div>
      </div>
      <div class="paper-rule" aria-hidden="true"></div>

      <div v-if="loading" class="paper-loading">作业加载中…</div>

      <template v-if="!loading">
        <!-- 日期筛选状态栏（右侧栏日历选中某天时出现；只报当天进度，
             清筛选的按钮在试卷头右侧，避免双份入口） -->
        <div v-if="dateFilter" class="filter-bar">
          <div class="filter-info">
            <span class="filter-title">{{ dateFilterLabel }} 发布的作业</span>
            <span class="filter-progress-text tnum">已完成 {{ dayProgress.done }} / 共 {{ dayProgress.total }} 份</span>
            <div class="progress-track">
              <div class="progress-fill" :style="{ width: `${dayProgress.total ? (dayProgress.done / dayProgress.total) * 100 : 0}%` }"></div>
            </div>
          </div>
        </div>

        <!-- 试卷正文：key 随筛选变化 → 轻翻页过渡；盖章只在首次加载（intro）时播 -->
        <div :key="dateFilter || 'all'" class="paper-body">
          <template v-if="assignments.length">
            <section
              v-for="(a, i) in assignments"
              :key="a.id"
              class="paper-item"
              :style="{ '--i': i }"
            >
              <div class="stamps" aria-hidden="true">
                <span
                  class="stamp"
                  :class="[`stamp--${stampOf(a).kind}`, { 'stamp--anim': intro }]"
                >{{ stampOf(a).text }}</span>
              </div>

              <h4 class="item-title">{{ a.title }}</h4>
              <p v-if="assignmentPreview(a)" class="assign-desc">{{ assignmentPreview(a) }}</p>
              <p v-if="a.mode === 'offline'" class="assign-offline">
                <AppIcon name="book" :size="14" />
                <span v-if="a.workbook_title">{{ a.workbook_title }}</span>
                <span v-if="a.page_range">{{ a.page_range }}</span>
                <span v-if="a.deadline">截止 {{ fmtTime(a.deadline) }}</span>
              </p>
              <div class="assign-meta">
                <span v-if="a.mode === 'offline'" class="badge badge-amber">线下练习</span>
                <span v-else class="badge badge-blue">{{ a.photo_required ? '拍照提交' : '线上作业' }}</span>
                <span class="badge badge-blue tnum">{{ a.question_count }} 道题</span>
                <span class="meta-progress tnum">已答 {{ doneCount(a) }}/{{ a.question_count }} 题</span>
                <span class="assign-time">{{ fmtTime(a.created_at) }} 发布</span>
              </div>
              <div class="item-foot">
                <router-link :to="`/student/submit?assignment_id=${a.id}`" class="btn">
                  {{ assignmentActionLabel(a) }}
                </router-link>
                <button
                  v-if="canSubmitStagedAssignment(a)"
                  type="button"
                  class="btn"
                  :disabled="submittingAssignments.has(a.id)"
                  @click="submitStagedAssignment(a)"
                >{{ submittingAssignments.has(a.id) ? '提交中…' : a.grading_status === 'failed' ? '重新开始批改' : '提交作业' }}</button>
              </div>
            </section>
          </template>

          <div v-else-if="dateFilter" class="paper-empty">
            这一天没有发布的作业，点上方「返回查看全部作业」看全部。
          </div>

          <div v-else-if="!assignments.length" class="paper-empty">
            老师还没有布置作业，稍后再来看看吧。
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useStudentStore } from '../../stores/student'
import type { Assignment } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'

const student = useStudentStore()

const assignments = ref<Assignment[]>([])
const loading = ref(false)
const error = ref('')
const submittingAssignments = ref<Set<number>>(new Set())
let gradingPollHandle: number | null = null

/** 盖章入场只在首次加载播一次；日期筛选变化后关掉，正文只做轻翻页过渡 */
const intro = ref(true)

/** 右侧栏日历选中的发布日期（yyyy-mm-dd，空 = 不筛选）——与日历共用 store 状态 */
const dateFilter = computed(() => student.assignmentDateFilter)

watch(dateFilter, () => {
  intro.value = false
  void loadAssignments()
})

const dateFilterLabel = computed(() => {
  if (!dateFilter.value) return ''
  const [y, m, d] = dateFilter.value.split('-')
  return `${y} 年 ${Number(m)} 月 ${Number(d)} 日`
})

/** 筛选当天（或全部）的完成进度：一份作业的全部题目都提交过 = 已完成 */
const dayProgress = computed(() => {
  let done = 0
  let total = 0
  for (const assignment of assignments.value) {
    total++
    if (assignment.question_count > 0 && doneCount(assignment) >= assignment.question_count) {
      done++
    }
  }
  return { done, total }
})

function clearFilter() {
  student.setAssignmentDateFilter('')
}

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

function assignmentPreview(a: Assignment): string {
  if (a.description?.trim()) return a.description.trim()
  const question = a.questions?.[0]
  if (!question) return ''
  const group = a.groups?.find((item) => item.id === question.group_id)
  return [group?.stem?.trim(), question.stem?.trim()].filter(Boolean).join(' ')
}

function doneCount(a: Assignment): number {
  return Math.max(a.submitted_count ?? 0, a.staged_count ?? 0)
}

function canSubmitStagedAssignment(a: Assignment): boolean {
  return a.question_count > 0 && (a.staged_count ?? 0) >= a.question_count
    && (a.grading_status === 'draft' || a.grading_status === 'failed')
}

function assignmentActionLabel(a: Assignment): string {
  if (a.grading_status === 'queued' || a.grading_status === 'processing') return '查看批改进度'
  if (a.grading_status === 'completed') return '查看批改结果'
  if (canSubmitStagedAssignment(a)) return '检查作答'
  if ((a.staged_count ?? 0) > 0) return '继续作答'
  return a.photo_required ? '拍照提交' : '在线答题'
}

async function submitStagedAssignment(a: Assignment) {
  if (!canSubmitStagedAssignment(a) || submittingAssignments.value.has(a.id)) return
  submittingAssignments.value = new Set(submittingAssignments.value).add(a.id)
  error.value = ''
  try {
    await student.submitAssignmentForGrading(a.id)
    await loadAssignments()
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = typeof detail === 'string' ? detail : '提交作业失败，请进入作答页检查后重试。'
  } finally {
    const next = new Set(submittingAssignments.value)
    next.delete(a.id)
    submittingAssignments.value = next
  }
}

/** 状态印章：已完成=红章 / 进行中·未开始=灰色铅笔描边章（待审核为另一颗琥珀章并列） */
function stampOf(a: Assignment): { kind: 'done' | 'doing' | 'todo'; text: string } {
  const total = a.question_count
  const done = doneCount(a)
  if (a.grading_status === 'queued' || a.grading_status === 'processing') return { kind: 'doing', text: '批改中' }
  if (a.grading_status === 'failed') return { kind: 'doing', text: '批改失败' }
  if (a.grading_status === 'draft' && (a.staged_count ?? 0) > 0 && done >= total) return { kind: 'doing', text: '待提交' }
  if (total > 0 && done >= total) return { kind: 'done', text: '已完成' }
  if (done > 0) return { kind: 'doing', text: '进行中' }
  return { kind: 'todo', text: '未开始' }
}

let assignmentLoadGeneration = 0

async function loadAssignments(showLoading = true) {
  const generation = ++assignmentLoadGeneration
  if (showLoading) loading.value = true
  error.value = ''
  try {
    const list = await student.fetchAssignments(
      true, false, true, false, dateFilter.value || undefined
    )
    if (generation === assignmentLoadGeneration) {
      assignments.value = list
      const hasActiveGrading = list.some((a) => a.grading_status === 'queued' || a.grading_status === 'processing')
      if (hasActiveGrading && gradingPollHandle === null) {
        gradingPollHandle = window.setInterval(() => { void loadAssignments(false) }, 3000)
      } else if (!hasActiveGrading && gradingPollHandle !== null) {
        window.clearInterval(gradingPollHandle)
        gradingPollHandle = null
      }
    }
  } catch (e) {
    if (generation === assignmentLoadGeneration) {
      error.value = '作业列表加载失败，请确认后端已启动。'
    }
    console.error(e)
  } finally {
    if (showLoading && generation === assignmentLoadGeneration) loading.value = false
  }
}

onMounted(() => { void loadAssignments() })
onBeforeUnmount(() => {
  assignmentLoadGeneration++
  if (gradingPollHandle !== null) window.clearInterval(gradingPollHandle)
})
</script>

<style scoped>
/* ---------- 试卷纸面 ---------- */
.paper {
  position: relative;
  background:
    radial-gradient(ellipse 90% 46% at 50% -12%, rgba(29, 78, 216, 0.035), transparent 70%),
    linear-gradient(180deg, #ffffff 0%, #fdfcf8 100%);
  border: 1px solid #e8e5dc;
  border-radius: var(--radius-detail);
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.05),
    0 14px 34px -10px rgba(15, 23, 42, 0.18),
    0 36px 68px -28px rgba(15, 23, 42, 0.14);
  padding: 26px 30px 30px 66px;
  margin-bottom: 16px;
  animation: paper-in 0.5s ease-out both;
}
/* 装订线：左侧竖直虚线 + 一道淡淡的红边线（作业纸） */
.paper::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 42px;
  border-left: 2px dashed #d5d8de;
}
.paper::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 48px;
  border-left: 1px solid rgba(220, 38, 38, 0.16);
}
@keyframes paper-in {
  from { opacity: 0; transform: translateY(-16px) rotate(-0.5deg); }
  to { opacity: 1; transform: translateY(0) rotate(0deg); }
}

/* 订书钉：金属渐变横钉 + 两只钉脚，略带倾斜与高光 */
.staple {
  position: absolute;
  top: -7px;
  left: 24px;
  width: 46px;
  height: 11px;
  border-radius: var(--radius-detail);
  transform: rotate(-14deg);
  background: linear-gradient(180deg, #f4f5f7 0%, #c9ced6 42%, #969ea9 58%, #d8dde3 100%);
  box-shadow:
    0 2px 3px rgba(15, 23, 42, 0.35),
    inset 0 1px 0 rgba(255, 255, 255, 0.85),
    inset 0 -1px 1px rgba(0, 0, 0, 0.2);
  z-index: 3;
}
.staple::before,
.staple::after {
  content: '';
  position: absolute;
  top: 8px;
  width: 5px;
  height: 9px;
  border-radius: var(--radius-micro);
  background: linear-gradient(180deg, #aeb5bf, #878e99);
  box-shadow: inset 0 0 1px rgba(0, 0, 0, 0.3);
}
.staple::before { left: 5px; }
.staple::after { right: 5px; }

/* 装订线竖排小字 */
.binding-word {
  position: absolute;
  left: 13px;
  top: 50%;
  transform: translateY(-50%);
  writing-mode: vertical-rl;
  letter-spacing: 10px;
  font-size: 11px;
  color: #c2c8d0;
  user-select: none;
}

/* 试卷头：居中标题 + 右侧计数，下面一道粗细双线 */
.paper-head {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: baseline;
}
.paper-title {
  font-size: 21px;
  font-weight: 800;
  letter-spacing: 6px;
  color: var(--text);
  text-align: center;
}
.paper-count {
  justify-self: end;
  font-size: 12.5px;
  color: var(--text-3);
}
.paper-head-right {
  justify-self: end;
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 34px;
}
/* 清筛选按钮：主色实心 + 轻投影，在纸面上跳得出来 */
.filter-clear-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
  box-shadow: var(--shadow);
}
.paper-rule {
  height: 4px;
  border-top: 2px solid #4b5563;
  border-bottom: 1px solid #4b5563;
  margin: 10px 0 14px;
}

.paper-loading {
  text-align: center;
  padding: 44px 0;
  color: var(--text-3);
  font-size: 14px;
  letter-spacing: 2px;
}

/* 正文翻页过渡（筛选切换时由 :key 重挂触发） */
.paper-body { animation: body-in 0.28s ease both; }
@keyframes body-in {
  from { opacity: 0; transform: translateY(7px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ---------- 大题条目 ---------- */
.paper-item {
  position: relative;
  padding: 20px 14px 18px 8px;
  border-bottom: 1px dashed #e4e2d9;
  border-radius: var(--radius-detail);
  content-visibility: auto;
  contain-intrinsic-size: auto 220px;
  transition: box-shadow 0.2s ease, transform 0.2s ease, background 0.2s ease;
}
.paper-item:last-child { border-bottom: none; }
.paper-item:hover {
  background: rgba(255, 255, 255, 0.92);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}
.item-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--text);
  padding-right: 158px;
  margin-bottom: 6px;
}
.paper-item .assign-desc {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
}
.paper-item .assign-meta { flex-wrap: wrap; margin-bottom: 12px; }
.meta-progress { font-size: 12.5px; color: var(--text-2); }
.item-foot { display: flex; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }
.item-foot .btn { min-width: 168px; }

.assign-offline {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  font-size: 13px; color: var(--amber-strong);
  background: var(--amber-bg); border-radius: var(--radius-control);
  padding: 7px 10px; margin-bottom: 10px;
}

/* ---------- 印章 ---------- */
.stamps {
  position: absolute;
  top: 16px;
  right: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  z-index: 2;
}
.stamp {
  --rot: -8deg;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  letter-spacing: 2.5px;
  white-space: nowrap;
  transform: rotate(var(--rot));
  mix-blend-mode: multiply;
  opacity: 0.92;
  text-shadow: 0 0 0.6px currentColor;
  user-select: none;
}
/* 已完成：红色圆章、双线边 */
.stamp--done {
  width: 58px;
  height: 58px;
  border-radius: 50%;
  border: 2.5px solid var(--red);
  outline: 1.2px solid var(--red);
  outline-offset: 2.5px;
  color: var(--red);
  font-size: 13.5px;
}
/* 待审核：琥珀方章、双线边 */
.stamp--pending {
  --rot: -13deg;
  padding: 5px 9px;
  border-radius: var(--radius-detail);
  border: 2px solid var(--amber);
  outline: 1px solid var(--amber);
  outline-offset: 2px;
  color: var(--amber);
  font-size: 12.5px;
}
/* 进行中/未开始：灰色铅笔描边章（虚线，像铅笔随手圈的） */
.stamp--doing,
.stamp--todo {
  --rot: -5deg;
  padding: 5px 10px;
  border-radius: var(--radius-detail);
  border: 1.6px dashed #9aa1ab;
  color: #838a94;
  font-size: 12.5px;
  font-weight: 700;
  opacity: 0.85;
}
/* 盖章动画：从放大砸下、一次小回弹；延迟随条目序号递增 */
.stamp--anim {
  animation: stamp-in 0.38s cubic-bezier(0.25, 1.4, 0.4, 1) both;
  animation-delay: calc(160ms + var(--i, 0) * 90ms);
}
@keyframes stamp-in {
  0% { opacity: 0; transform: rotate(var(--rot)) scale(1.7); }
  55% { opacity: 1; transform: rotate(var(--rot)) scale(0.93); }
  76% { transform: rotate(var(--rot)) scale(1.045); }
  100% { opacity: 0.92; transform: rotate(var(--rot)) scale(1); }
}

/* ---------- 日期筛选条 / 空状态 ---------- */
.filter-bar {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  background: var(--primary-50); border: 1px solid var(--blue-bg); border-radius: var(--radius-control);
  margin-bottom: 8px; padding: 14px 18px;
}
.filter-info { display: flex; align-items: center; gap: 14px; flex: 1; min-width: 240px; flex-wrap: wrap; }
.filter-title { font-size: 15px; font-weight: 700; }
.filter-progress-text { font-size: 13.5px; color: var(--text-2); }
.progress-track {
  flex: 1; min-width: 120px; height: 8px; border-radius: var(--radius-pill);
  background: #fff; overflow: hidden;
}
.progress-fill {
  height: 100%; border-radius: var(--radius-pill); background: var(--primary);
  transition: width 0.35s ease;
}
.paper-empty {
  text-align: center;
  padding: 46px 12px 40px;
  color: var(--text-3);
  font-size: 14.5px;
  letter-spacing: 1px;
}
.paper-empty::before {
  content: '';
  display: block;
  width: 120px;
  margin: 0 auto 16px;
  border-top: 2px dashed #d8d5cc;
}

/* ---------- 移动端 ---------- */
@media (max-width: 640px) {
  .paper { padding: 20px 16px 22px 46px; }
  .paper::before { left: 27px; }
  .paper::after { left: 33px; }
  .binding-word { left: 5px; font-size: 10px; letter-spacing: 7px; }
  .staple { left: 12px; width: 40px; }
  .paper-title { font-size: 18px; letter-spacing: 4px; }
  /* 移动端：试卷头改纵排居中，清筛选按钮落在标题下方一行，够得着、不挤印章 */
  .paper-head { display: flex; flex-direction: column; align-items: center; gap: 8px; }
  .paper-head-left { display: none; }
  .paper-head-right { justify-self: auto; flex-wrap: wrap; justify-content: center; }
  .item-title { padding-right: 108px; font-size: 16px; }
  .stamps { top: 14px; right: 6px; gap: 7px; }
  .stamp--done { width: 46px; height: 46px; font-size: 11.5px; letter-spacing: 1.5px; }
  .stamp--pending, .stamp--doing, .stamp--todo { font-size: 11px; padding: 4px 7px; letter-spacing: 1.5px; }
  .item-foot .btn { width: 100%; min-width: 0; }
  .item-foot { display: grid; grid-template-columns: 1fr; }
}

@media (prefers-reduced-motion: reduce) {
  .paper, .paper-body, .stamp--anim { animation: none; }
  .paper-item, .progress-fill { transition: none; }
  .paper-item:hover { transform: none; }
}
</style>
