<!-- 订正便利贴墙（v0.9.3）：一题一张便利贴贴在板面上错落排布。
     点待订正的贴 → 先播「撕下来」动画（掀角 → 向下撕落），动画结束才 emit pick，
     由订正页切到该题的修正工作区；已订正的贴换柔和色 + 盖对勾印，点开看诊断详情。
     配色与 RightRail 便利贴统一：#fff3b8 / #ffdce8 / #d6e9ff 循环 + 墨色 #3f3a2a。
     prefers-reduced-motion 时不播动画、点按直接 emit。 -->
<template>
  <div class="wall">
    <div v-if="notes.length" class="wall-grid">
      <button
        v-for="(n, i) in notes"
        :key="n.errorId"
        type="button"
        class="note"
        :class="[`note-c${i % 3}`, { fixed: n.isFixed, tearing: tearingId === n.errorId }]"
        :style="{ '--rot': `${ROTATIONS[i % ROTATIONS.length]}deg` }"
        :aria-label="n.isFixed ? `已订正：${n.stem}，查看诊断详情` : `撕下订正：${n.stem}`"
        @click="onNoteClick(n)"
      >
        <span class="note-top">
          <ErrorTypeBadge :type="n.errorType" />
          <span v-if="n.isStubborn && !n.isFixed" class="note-stubborn">需要加固</span>
        </span>
        <span class="note-stem">{{ n.stem }}</span>
        <span v-if="n.stepText" class="note-step">出错步骤：{{ n.stepText }}</span>
        <span class="note-meta">{{ n.knowledgePoint }} · {{ n.assignmentTitle }}</span>
        <span class="note-meta">{{ n.dateLabel }}</span>
        <span class="note-foot">
          <template v-if="n.isFixed"><AppIcon name="check" :size="13" /> 已订正 · 点一下看诊断详情</template>
          <template v-else><AppIcon name="edit" :size="13" /> 点一下，撕下来订正</template>
        </span>
        <span v-if="n.isFixed" class="note-seal"><AppIcon name="check" :size="17" /></span>
      </button>
    </div>
    <div v-else class="wall-empty">
      <div class="note note-c0 note-hint">
        <slot name="empty" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from './icons/AppIcon.vue'
import ErrorTypeBadge from './ErrorTypeBadge.vue'

export interface CorrectionNote {
  errorId: number
  submissionId: number
  /** 题干摘录（一眼认出这题） */
  stem: string
  /** 出错步骤（与题干相同或为空时传空串，贴面不重复显示） */
  stepText: string
  knowledgePoint: string
  errorType: string
  assignmentTitle: string
  dateLabel: string
  isFixed: boolean
  isStubborn: boolean
}

defineProps<{ notes: CorrectionNote[] }>()
const emit = defineEmits<{
  /** 待订正贴被撕下（动画播完）→ 父页进入该题修正工作区 */
  pick: [errorId: number]
  /** 已订正贴被点 → 父页跳诊断详情 */
  view: [submissionId: number]
}>()

/** 每张贴的固定倾斜角（按序号循环，错落但不乱） */
const ROTATIONS = [-2, 1.5, -1, 2.2, -1.5, 0.8, -2.4, 1.2]
/** 正在撕的那张贴（撕完才 emit，期间锁住其他点按） */
const tearingId = ref<number | null>(null)

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
  border-radius: 18px;
  padding: 28px 22px 24px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.65), inset 0 0 28px rgba(122, 102, 52, 0.07),
    0 1px 2px rgba(16, 24, 40, 0.05);
}
.wall-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(218px, 1fr));
  gap: 30px 22px;
}

/* ---------- 便利贴 ---------- */
.note {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-height: 178px;
  padding: 20px 16px 14px;
  border: 0;
  font: inherit;
  text-align: left;
  color: #3f3a2a;
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
.note-c0 { background: linear-gradient(180deg, #fff6c4, #fff3b8); }
.note-c1 { background: linear-gradient(180deg, #ffe3ee, #ffdce8); }
.note-c2 { background: linear-gradient(180deg, #e0efff, #d6e9ff); }

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
.note-stubborn {
  font-size: 11.5px; font-weight: 700; color: #92400e;
  background: rgba(217, 119, 6, 0.16); padding: 2px 8px; border-radius: 999px;
}
.note-stem {
  font-size: 15px; font-weight: 700; line-height: 1.45;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.note-step {
  font-size: 12.5px; color: rgba(63, 58, 42, 0.72);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.note-meta {
  font-size: 12.5px; color: rgba(63, 58, 42, 0.78);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.note-foot {
  margin-top: auto;
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
