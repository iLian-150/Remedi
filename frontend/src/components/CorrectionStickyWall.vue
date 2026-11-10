<!-- 订正便利贴墙：每张只显示作业、题号、错误类型和日期。
     点待订正的贴 → 先播「撕下来」动画（掀角 → 向下撕落），动画结束才 emit pick，
     由订正页切到该题的修正工作区；已订正的贴换柔和色 + 盖对勾印，点开看诊断详情。
     配色与 RightRail 便利贴统一：var(--note-yellow) / var(--note-pink) / var(--note-blue) 循环 + 墨色 var(--note-ink)。
     prefers-reduced-motion 时不播动画、点按直接 emit。 -->
<template>
  <div class="wall">
    <div v-if="notes.length" class="wall-grid">
      <button
        v-for="entry in notes"
        :key="entry.note.errorId"
        type="button"
        class="note"
        :class="[
          `note-c${entry.index % 3}`,
          { fixed: entry.note.isFixed, tearing: tearingId === entry.note.errorId },
        ]"
        :style="{ '--rot': `${ROTATIONS[entry.index % ROTATIONS.length]}deg` }"
        :aria-label="noteAriaLabel(entry.note)"
        :title="entry.note.assignmentTitle"
        @click="onNoteClick(entry.note)"
      >
        <span class="note-assignment">{{ entry.note.assignmentTitle }}</span>
        <strong class="note-question">第 {{ entry.note.questionOrder }} 题</strong>
        <span class="note-top"><ErrorTypeBadge :type="entry.note.errorType" /></span>
        <span class="note-date">{{ entry.note.dateLabel }}</span>
        <span v-if="entry.note.isFixed" class="note-foot"><AppIcon name="check" :size="13" /> 已订正</span>
        <span v-if="entry.note.isFixed" class="note-seal"><AppIcon name="check" :size="17" /></span>
      </button>
    </div>
    <div v-else class="wall-empty">
      <div class="note note-c0 note-hint">
        <slot name="empty" />
      </div>
    </div>
    <button
      v-if="hasMore"
      type="button"
      class="wall-more"
      :disabled="loadingMore"
      @click="emit('show-more')"
    >
      {{ loadingMore ? '正在加载…' : `继续显示错题（${loadedCount} / ${totalCount}）` }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from './icons/AppIcon.vue'
import ErrorTypeBadge from './ErrorTypeBadge.vue'

export interface CorrectionNote {
  errorId: number
  submissionId: number
  subject: string
  subjectName: string
  assignmentId: number
  assignmentTitle: string
  questionOrder: number
  errorType: string
  reviewStatus?: 'pending' | 'approved'
  dateLabel: string
  isFixed: boolean
}

export interface CorrectionSubjectGroup {
  key: string
  label: string
  assignments: Array<{ id: number; title: string; notes: CorrectionNote[] }>
}

const props = defineProps<{
  groups: CorrectionSubjectGroup[]
  totalCount: number
  hasMore: boolean
  loadingMore: boolean
}>()
const notes = computed(() => {
  let index = 0
  return props.groups.flatMap((subject) => subject.assignments.flatMap((assignment) =>
    assignment.notes.map((note) => ({ note, index: index++ })),
  ))
})
const loadedCount = computed(() => notes.value.length)
const emit = defineEmits<{
  /** 待订正贴被撕下（动画播完）→ 父页进入该题修正工作区 */
  pick: [errorId: number]
  /** 已订正贴被点 → 父页跳诊断详情 */
  view: [submissionId: number]
  'show-more': []
}>()

/** 每张贴的固定倾斜角（按序号循环，错落但不乱） */
const ROTATIONS = [-2, 1.5, -1, 2.2, -1.5, 0.8, -2.4, 1.2]
/** 正在撕的那张贴（撕完才 emit，期间锁住其他点按） */
const tearingId = ref<number | null>(null)

function noteAriaLabel(note: CorrectionNote) {
  const status = note.isFixed ? '已订正，查看诊断详情' : '待订正'
  return `${note.assignmentTitle}，第 ${note.questionOrder} 题，${note.errorType}，${note.dateLabel}，${status}`
}

function onNoteClick(n: CorrectionNote) {
  if (tearingId.value !== null) return
  if (n.isFixed) {
    emit('view', n.submissionId)
    return
  }
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    emit('pick', n.errorId)
    return
  }
  tearingId.value = n.errorId
  window.setTimeout(() => {
    tearingId.value = null
    emit('pick', n.errorId)
  }, 460)
}
</script>

<style scoped>
/* ---------- 板面 ---------- */
.wall {
  background: linear-gradient(180deg, #f5f1e6, #eee8d8);
  border: 1px solid #e3dcc4;
  border-radius: var(--radius-surface);
  padding: 28px 22px 24px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.65), inset 0 0 28px rgba(122, 102, 52, 0.07),
    0 1px 2px rgba(16, 24, 40, 0.05);
}
.wall-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(218px, 1fr));
  gap: 30px 22px;
}
.wall-more {
  display: block;
  width: min(420px, 100%);
  margin: 22px auto 0;
  padding: 10px 16px;
  border: 1px solid #d8d0ba;
  border-radius: var(--radius-control);
  background: rgba(255, 255, 255, 0.62);
  color: #57503c;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.wall-more:hover { background: #fff; border-color: #b9ad8c; }
.wall-more:disabled { opacity: 0.65; cursor: default; }

/* ---------- 便利贴 ---------- */
.note {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-height: 164px;
  padding: 20px 16px 14px;
  border: 0;
  font: inherit;
  text-align: left;
  color: var(--note-ink);
  cursor: pointer;
  appearance: none;
  transform: rotate(var(--rot, 0deg));
  box-shadow: 2px 4px 10px rgba(63, 58, 42, 0.18);
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}
/* 顶部胶带 */
.note::before {
  content: '';
  position: absolute;
  top: -11px;
  left: 50%;
  width: 86px;
  height: 24px;
  transform: translateX(-50%) rotate(-2.5deg);
  background: linear-gradient(180deg, rgba(255, 252, 235, 0.78), rgba(245, 238, 200, 0.55));
  box-shadow: 0 1px 3px rgba(63, 58, 42, 0.16);
  clip-path: polygon(2% 0, 98% 10%, 100% 100%, 0 90%);
  pointer-events: none;
}
.note:hover:not(.tearing) {
  transform: rotate(0deg) translateY(-4px);
  box-shadow: 4px 10px 20px rgba(63, 58, 42, 0.24);
  z-index: 1;
}
.note-c0 { background: var(--note-yellow); }
.note-c1 { background: var(--note-pink); }
.note-c2 { background: var(--note-blue); }

/* 已订正：纸色柔和下来（去饱和）+ 对勾印 */
.note.fixed { filter: saturate(0.48) brightness(1.045); }
.note-seal {
  position: absolute;
  right: 12px;
  bottom: 12px;
  width: 38px;
  height: 38px;
  border: 2.5px solid var(--green);
  border-radius: 50%;
  color: var(--green);
  background: rgba(255, 255, 255, 0.25);
  display: grid;
  place-items: center;
  transform: rotate(-14deg);
  opacity: 0.88;
  mix-blend-mode: multiply;
  pointer-events: none;
}

/* 撕下动画：先掀角，再向下撕落淡出；支点在顶部胶带处 */
.note.tearing {
  animation: tear-off 0.46s cubic-bezier(0.55, 0.06, 0.75, 0.4) forwards;
  transform-origin: 82% -6%;
  z-index: 3;
  pointer-events: none;
}
@keyframes tear-off {
  0% { transform: rotate(var(--rot, 0deg)) translateY(0); opacity: 1; }
  22% { transform: rotate(calc(var(--rot, 0deg) - 4deg)) translateY(-5px); opacity: 1; }
  55% { transform: rotate(3deg) translateY(28px); opacity: 0.92; }
  100% { transform: rotate(9deg) translate(16px, 132px); opacity: 0; }
}

/* ---------- 贴面内容 ---------- */
.note-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.note-assignment { overflow: hidden; color: rgba(63, 58, 42, 0.72); font-size: 12px; line-height: 1.5; text-overflow: ellipsis; white-space: nowrap; }
.note-question { color: var(--note-ink); font-size: 17px; font-weight: 750; line-height: 1.35; }
.note-date { margin-top: auto; color: rgba(63, 58, 42, 0.72); font-size: 12px; }
.note-foot {
  margin-top: 0;
  display: flex; align-items: center; gap: 5px;
  font-size: 12.5px; font-weight: 600; color: rgba(63, 58, 42, 0.66);
}

/* ---------- 空态提示贴 ---------- */
.wall-empty { display: flex; justify-content: center; padding: 10px 0 6px; }
.note-hint {
  --rot: -1.5deg;
  width: min(360px, 100%);
  min-height: 0;
  cursor: default;
  font-size: 14px;
  line-height: 1.65;
}
.note-hint:hover { transform: rotate(var(--rot)); box-shadow: 2px 4px 10px rgba(63, 58, 42, 0.18); }

/* ---------- 移动端 ---------- */
@media (max-width: 640px) {
  .wall { padding: 22px 14px 18px; }
  .wall-grid { grid-template-columns: repeat(auto-fill, minmax(158px, 1fr)); gap: 24px 14px; }
  .note { min-height: 160px; padding: 18px 13px 12px; }
}
@media (max-width: 400px) {
  .wall-grid { grid-template-columns: 1fr; }
}

/* ---------- 减少动态偏好 ---------- */
@media (prefers-reduced-motion: reduce) {
  .note { transition: none; }
  .note:hover:not(.tearing) { transform: rotate(var(--rot, 0deg)); }
  .note.tearing { animation: none; }
}
</style>
