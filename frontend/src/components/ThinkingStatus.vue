<template>
  <div class="thinking-status" role="status" aria-live="polite" aria-atomic="true">
    <Transition name="thinking-swap" mode="out-in">
      <span :key="currentPhrase" class="thinking-phrase">{{ currentPhrase }}</span>
    </Transition>
    <span class="thinking-dots" aria-hidden="true">
      <i></i><i></i><i></i>
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

const PHRASES = [
  '我正在思考',
  '等等我找一下答案',
  '正在整理思路',
  '我再检查一下'
]

const phraseIndex = ref(0)
const currentPhrase = computed(() => PHRASES[phraseIndex.value])
let phraseTimer: number | undefined

onMounted(() => {
  phraseTimer = window.setInterval(() => {
    phraseIndex.value = (phraseIndex.value + 1) % PHRASES.length
  }, 2400)
})

onUnmounted(() => {
  if (phraseTimer !== undefined) window.clearInterval(phraseTimer)
})
</script>

<style scoped>
.thinking-status {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  gap: 8px;
  color: var(--text-2);
  font-size: 14px;
  line-height: 1.5;
}
.thinking-phrase { display: inline-block; min-width: 9em; }
.thinking-dots { display: inline-flex; align-items: center; gap: 3px; }
.thinking-dots i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--primary);
  animation: thinking-bounce 0.9s ease-in-out infinite;
}
.thinking-dots i:nth-child(2) { animation-delay: 0.12s; }
.thinking-dots i:nth-child(3) { animation-delay: 0.24s; }
.thinking-swap-enter-active,
.thinking-swap-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }
.thinking-swap-enter-from { opacity: 0; transform: translateY(4px); }
.thinking-swap-leave-to { opacity: 0; transform: translateY(-4px); }
@keyframes thinking-bounce {
  0%, 60%, 100% { opacity: 0.38; transform: translateY(0); }
  30% { opacity: 1; transform: translateY(-3px); }
}
@media (prefers-reduced-motion: reduce) {
  .thinking-dots i { animation: none; opacity: 0.7; }
  .thinking-swap-enter-active,
  .thinking-swap-leave-active { transition: none; }
}
</style>
