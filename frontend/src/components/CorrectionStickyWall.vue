<template>
  <section class="correction-wall" aria-label="错题便利贴墙" :aria-busy="loadingMore">
    <div v-if="notes.length" class="correction-wall-grid">
      <button
        v-for="(item, index) in notes"
        :key="item.id"
        type="button"
        class="correction-note"
        :class="[`note-c${index % 3}`, { fixed: item.corrected }]"
        :style="{ '--rotation': `${ROTATIONS[index % ROTATIONS.length]}deg` }"
        :aria-label="noteAriaLabel(item)"
        @click="emit('open', item)"
      >
        <span class="correction-note-top">
          <strong>第 {{ item.question_order }} 题</strong>
          <ErrorTypeBadge :type="item.error_type" />
        </span>
        <span class="correction-note-stem">{{ item.question_stem || (item.image_url ? '图片题目' : '题目暂未记录') }}</span>
        <span class="correction-note-footer">
          <time :datetime="item.submitted_at ?? item.created_at">{{ dateLabel(item) }}</time>
          <span>{{ item.corrected ? '查看诊断' : '去订正' }} <AppIcon name="chevron-right" :size="14" /></span>
        </span>
        <span v-if="item.corrected" class="correction-note-seal" aria-hidden="true">
          <AppIcon name="check" :size="17" />
        </span>
      </button>
    </div>
    <div v-else class="correction-wall-empty">
      <slot name="empty">这份作业暂时没有错题。</slot>
    </div>

    <button
      v-if="hasMore"
      type="button"
      class="correction-wall-more"
      :disabled="loadingMore"
      @click="emit('show-more')"
    >
      {{ loadingMore ? '正在加载…' : `继续显示错题（${notes.length} / ${totalCount}）` }}
    </button>
  </section>
</template>

<script setup lang="ts">
import type { StudentCorrectionWallItem } from '../api/types'
import AppIcon from './icons/AppIcon.vue'
import ErrorTypeBadge from './ErrorTypeBadge.vue'

defineProps<{
  notes: StudentCorrectionWallItem[]
  totalCount: number
  hasMore: boolean
  loadingMore: boolean
}>()

const emit = defineEmits<{
  open: [item: StudentCorrectionWallItem]
  'show-more': []
}>()

const ROTATIONS = [-1.4, 1.1, -0.7, 1.6, -1, 0.6]

function dateLabel(item: StudentCorrectionWallItem): string {
  const value = item.submitted_at ?? item.created_at
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : `${date.getMonth() + 1}月${date.getDate()}日`
}

function noteAriaLabel(item: StudentCorrectionWallItem): string {
  const state = item.corrected ? '已订正，查看诊断' : '待订正'
  const stem = item.question_stem || (item.image_url ? '图片题目' : '题目暂未记录')
  return `${item.assignment_title}，第 ${item.question_order} 题，${item.error_type}，${state}：${stem}`
}
</script>

<style scoped>
.correction-wall {
  padding: 22px 18px 20px;
  border: 1px solid var(--border);
  border-radius: var(--radius-surface);
  background: color-mix(in srgb, var(--note-yellow) 12%, var(--card));
}
.correction-wall-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 230px), 1fr));
  align-items: stretch;
  gap: 28px 22px;
}
.correction-note {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 198px;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
  padding: 24px 18px 16px;
  border: 1px solid color-mix(in srgb, var(--note-ink) 8%, transparent);
  border-radius: var(--radius-control);
  color: var(--note-ink);
  background: var(--note-paper, var(--note-yellow));
  box-shadow: var(--shadow-md);
  cursor: pointer;
  font: inherit;
  text-align: left;
  transform: rotate(var(--rotation, 0deg));
  transition: transform .18s ease, box-shadow .18s ease;
}
.correction-note::before {
  position: absolute;
  top: -8px;
  left: 50%;
  width: 72px;
  height: 19px;
  border: 1px solid color-mix(in srgb, var(--note-ink) 7%, transparent);
  background: color-mix(in srgb, var(--note-yellow) 72%, var(--card));
  box-shadow: var(--shadow);
  content: "";
  pointer-events: none;
  transform: translateX(-50%) rotate(-2deg);
}
.correction-note::after {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 18px;
  height: 18px;
  border-radius: 0 0 var(--radius-control) 0;
  background: linear-gradient(135deg, transparent 49%, color-mix(in srgb, var(--card) 72%, var(--note-paper)) 50%, var(--note-paper) 100%);
  content: "";
  pointer-events: none;
}
.note-c0 { --note-paper: var(--note-yellow); }
.note-c1 { --note-paper: var(--note-pink); }
.note-c2 { --note-paper: var(--note-blue); }
.correction-note.fixed { filter: saturate(.58) brightness(1.035); }
.correction-note-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.correction-note-top > strong { font-size: 15px; font-weight: 750; }
.correction-note-stem {
  display: -webkit-box;
  overflow: hidden;
  color: var(--note-ink);
  font-size: 14px;
  font-weight: 650;
  line-height: 1.55;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}
.correction-note-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: auto;
  padding-top: 5px;
  color: color-mix(in srgb, var(--note-ink) 72%, transparent);
  font-size: 12px;
}
.correction-note-footer > span { display: inline-flex; align-items: center; gap: 2px; font-weight: 700; }
.correction-note-seal {
  position: absolute;
  right: 12px;
  bottom: 34px;
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 2px solid var(--green);
  border-radius: 50%;
  color: var(--green);
  background: color-mix(in srgb, var(--card) 30%, transparent);
  opacity: .8;
  pointer-events: none;
  transform: rotate(-12deg);
}
.correction-note.fixed .correction-note-footer { padding-right: 38px; }
.correction-note:focus-visible { outline: 2px solid var(--primary); outline-offset: 4px; }
.correction-wall-empty { padding: 32px 16px; color: var(--text-2); text-align: center; }
.correction-wall-more {
  display: block;
  width: min(420px, 100%);
  min-height: 40px;
  margin: 23px auto 0;
  padding: 9px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  color: var(--primary);
  background: var(--card);
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  font-weight: 650;
}
.correction-wall-more:disabled { color: var(--text-3); cursor: wait; }

@media (hover: hover) {
  .correction-note:hover { z-index: 1; box-shadow: var(--shadow-lg); transform: translateY(-4px) rotate(0); }
  .correction-wall-more:hover { border-color: var(--border-strong); background: var(--primary-50); }
}
@media (max-width: 640px) {
  .correction-wall { padding: 20px 13px 16px; }
  .correction-wall-grid { grid-template-columns: repeat(auto-fill, minmax(min(100%, 180px), 1fr)); gap: 24px 14px; }
  .correction-note { min-height: 196px; padding-inline: 14px; }
}
@media (max-width: 400px) {
  .correction-wall-grid { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .correction-note { transition: none; }
  .correction-note:hover { transform: rotate(var(--rotation, 0deg)); }
}
</style>
