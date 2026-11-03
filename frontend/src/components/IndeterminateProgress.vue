<template>
  <div class="progress-track" role="progressbar" :aria-label="label"><span /></div>
</template>
<script setup lang="ts">
defineProps<{ label: string }>()
</script>
<style scoped>
.progress-track { height: 7px; overflow: hidden; border-radius: 999px; background: var(--gray-bg); }
.progress-track span { display: block; width: 38%; height: 100%; border-radius: inherit; background: var(--primary); animation: sweep 1.35s ease-in-out infinite; }
@keyframes sweep { from { transform: translateX(-110%); } to { transform: translateX(280%); } }
@media (prefers-reduced-motion: reduce) { .progress-track span { animation: none; width: 100%; } }
</style>
