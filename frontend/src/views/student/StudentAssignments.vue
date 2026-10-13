<!-- 学生端：作业列表 —— 交作业的统一入口
     数据源：GET /api/student/assignments（契约 3.1）
     v0.2.1 曾在页内放作业日历；v0.3.0 日历迁至右侧栏；v0.3.1 日历只在本页右栏出现，
     点选日期 → store.assignmentDateFilter 生效 → 本页按发布日期筛选并显示当天完成进度，
     「返回查看全部作业」清掉筛选。卡片按钮按作业模式分文案（v0.9.2：线上作业=
     「在线作答」、线下练习册=「拍照批改」），均进入 /student/submit?assignment_id=
     v0.9.3 试卷化：列表区整张做成「钉好的试卷」——纸面+订书钉+装订线+试卷头，
     每份作业是一道大题（中文题号），状态改用印章（已完成=红章、待审核=琥珀章、
     未开始/进行中=灰色铅笔描边章）；入场时试卷落下、印章逐个盖下（仅首次加载，
     日期筛选切换只做轻翻页过渡不再重复盖章）。
     v0.9.3 修复：「返回查看全部作业」原先只是筛选条里的一个低调小按钮、排在提示条
     下面，用户找不到；已移到试卷头右侧、改主色醒目按钮（仅筛选生效时出现），
     筛选条只保留当天的进度信息。 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>作业列表</h2>
      <p class="page-sub">选择一份作业开始作答，系统会自动批改；判断不确定的作答会送老师复核。</p>
    </div>

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
        <p class="rail-note"><AppIcon name="calendar" :size="15" /> 作业日历在右侧栏，点选任意一天即可只看当天发布的作业。</p>

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
          <template v-if="visibleAssignments.length">
            <section
              v-for="(a, i) in visibleAssignments"
              :key="a.id"
              class="paper-item"
              :style="{ '--i': i }"
            >
              <div class="stamps" aria-hidden="true">
                <span
                  v-if="hasPending(a)"
                  class="stamp stamp--pending"
                  :class="{ 'stamp--anim': intro }"
                  title="有提交待老师审核"
                >待审核</span>
                <span
                  class="stamp"
                  :class="[`stamp--${stampOf(a).kind}`, { 'stamp--anim': intro }]"
                >{{ stampOf(a).text }}</span>
              </div>

              <h4 class="item-title">
                <span class="item-no">{{ cnNum(i + 1) }}、</span>{{ a.title }}
              </h4>
              <p class="assign-desc">{{ a.description || '暂无说明' }}</p>
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
                <router-link :to="`/student/submit?assignment_id=${a.id}`">
                  <button class="btn">{{ a.photo_required ? '拍照批改' : '在线作答' }}</button>
                </router-link>
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
import { computed, onMounted, ref, watch } from 'vue'
import { useStudentStore } from '../../stores/student'
import type { Assignment } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'

const student = useStudentStore()

const assignments = ref<Assignment[]>([])
const loading = ref(false)
const error = ref('')

/** 盖章入场只在首次加载播一次；日期筛选变化后关掉，正文只做轻翻页过渡 */
const intro = ref(true)

/** 右侧栏日历选中的发布日期（yyyy-mm-dd，空 = 不筛选）——与日历共用 store 状态 */
const dateFilter = computed(() => student.assignmentDateFilter)

watch(dateFilter, () => {
  intro.value = false
})

const visibleAssignments = computed(() =>
  dateFilter.value
    ? assignments.value.filter((a) => a.created_at.slice(0, 10) === dateFilter.value)
    : assignments.value
)

const dateFilterLabel = computed(() => {
  if (!dateFilter.value) return ''
  const [y, m, d] = dateFilter.value.split('-')
  return `${y} 年 ${Number(m)} 月 ${Number(d)} 日`
})

/** 筛选当天（或全部）的完成进度：一份作业的全部题目都提交过 = 已完成 */
const dayProgress = computed(() => {
  const total = visibleAssignments.value.length
  const done = visibleAssignments.value.filter(
    (a) => a.question_count > 0 && doneCount(a) >= a.question_count
  ).length
  return { done, total }
})

function clearFilter() {
  student.setAssignmentDateFilter('')
}

/** 每份作业的题目 id 集合（由作业详情拼装，供完成状态展示） */
const questionIdsByAssignment = ref<Record<number, number[]>>({})
const doneQids = ref<Set<number>>(new Set())
/** v0.9.0：最新一次提交还在等老师审核的题目（据此盖「待审核」琥珀章） */
const pendingQids = ref<Set<number>>(new Set())

/** 这份作业里有没有题目在等老师审核 */
function hasPending(a: Assignment): boolean {
  const qids = questionIdsByAssignment.value[a.id] ?? []
  return qids.some((id) => pendingQids.value.has(id))
}

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

function doneCount(a: Assignment): number {
  const qids = questionIdsByAssignment.value[a.id] ?? []
  return qids.filter((id) => doneQids.value.has(id)).length
}

/** 大题号：中文数字（一、二、三……，支持到九十九） */
function cnNum(n: number): string {
  const d = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九']
  if (n < 10) return d[n]
  if (n < 20) return '十' + (n % 10 ? d[n % 10] : '')
  const t = Math.floor(n / 10)
  const o = n % 10
  return d[t] + '十' + (o ? d[o] : '')
}

/** 状态印章：已完成=红章 / 进行中·未开始=灰色铅笔描边章（待审核为另一颗琥珀章并列） */
function stampOf(a: Assignment): { kind: 'done' | 'doing' | 'todo'; text: string } {
  const total = a.question_count
  const done = doneCount(a)
  if (total > 0 && done >= total) return { kind: 'done', text: '已完成' }
  if (done > 0) return { kind: 'doing', text: '进行中' }
  return { kind: 'todo', text: '未开始' }
}

onMounted(async () => {
  loading.value = true
  try {
    const list = await student.fetchAssignments(true, true)
    assignments.value = list
    list.forEach((assignment) => {
      assignment.submitted_question_ids?.forEach((id) => doneQids.value.add(id))
      assignment.pending_question_ids?.forEach((id) => pendingQids.value.add(id))
      questionIdsByAssignment.value[assignment.id] =
        (assignment.questions ?? []).map((question) => question.id)
    })
  } catch (e) {
    error.value = '作业列表加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
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
  border-radius: 5px;
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
  border-radius: 6px;
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
  border-radius: 2px;
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
  box-shadow: 0 5px 14px -5px rgba(29, 78, 216, 0.55);
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
  border-radius: 8px;
  transition: box-shadow 0.2s ease, transform 0.2s ease, background 0.2s ease;
}
.paper-item:last-child { border-bottom: none; }
.paper-item:hover {
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 8px 20px -10px rgba(15, 23, 42, 0.22);
  transform: translateY(-1px);
}
.item-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--text);
  padding-right: 158px;
  margin-bottom: 6px;
}
.item-no { font-weight: 800; }
.paper-item .assign-desc { flex: none; }
.paper-item .assign-meta { flex-wrap: wrap; margin-bottom: 12px; }
.meta-progress { font-size: 12.5px; color: var(--text-2); }
.item-foot { display: flex; justify-content: flex-end; }
.item-foot .btn { min-width: 168px; }

.assign-offline {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  font-size: 13px; color: #92400E;
  background: var(--amber-bg); border-radius: 8px;
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
  border-radius: 5px;
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
  border-radius: 5px;
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

/* ---------- 纸面上的提示条 / 筛选条 / 空状态 ---------- */
.rail-note {
  display: flex; align-items: center; gap: 7px;
  font-size: 13.5px; color: var(--text-2);
  background: #f8fafc; border: 1px dashed #d8dee9; border-radius: 10px;
  padding: 10px 14px; margin-bottom: 16px;
}
.filter-bar {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  background: var(--primary-50); border: 1px solid #dbeafe; border-radius: 10px;
  margin-bottom: 8px; padding: 14px 18px;
}
.filter-info { display: flex; align-items: center; gap: 14px; flex: 1; min-width: 240px; flex-wrap: wrap; }
.filter-title { font-size: 15px; font-weight: 700; }
.filter-progress-text { font-size: 13.5px; color: var(--text-2); }
.progress-track {
  flex: 1; min-width: 120px; height: 8px; border-radius: 4px;
  background: #fff; overflow: hidden;
}
.progress-fill {
  height: 100%; border-radius: 4px; background: var(--primary);
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
  .item-foot { display: block; }
  .item-foot a { display: block; }
}

@media (prefers-reduced-motion: reduce) {
  .paper, .paper-body, .stamp--anim { animation: none; }
  .paper-item, .progress-fill { transition: none; }
  .paper-item:hover { transform: none; }
}
</style>
