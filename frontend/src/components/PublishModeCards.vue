<template>
  <div class="mode-grid">
    <button type="button" class="mode-card" @click="$emit('choose', 'online')">
      <span class="mode-icon"><AppIcon name="edit" :size="22" /></span>
      <span class="mode-name">线上作业</span>
      <span class="mode-desc">在这里逐题录入（或拍照识别）题目，学生在系统里在线作答。</span>
      <span class="mode-enter">进入发布 <AppIcon name="arrow-right" :size="15" /></span>
    </button>
    <button type="button" class="mode-card" @click="$emit('choose', 'offline')">
      <span class="mode-icon"><AppIcon name="book" :size="22" /></span>
      <span class="mode-name">线下作业 · 练习册</span>
      <span class="mode-desc">作业来自纸质练习册：选择练习册、填写页码，识别题目后发布，学生拍照提交。</span>
      <span class="mode-enter">进入发布 <AppIcon name="arrow-right" :size="15" /></span>
    </button>
  </div>
  <p class="mode-hint">可发布多学科作业。线上作业支持在线答题，线下作业通过拍照提交。</p>
</template>
<script setup lang="ts">
import AppIcon from './icons/AppIcon.vue'
defineEmits<{ choose: [mode: 'online' | 'offline'] }>()
</script>
<style scoped>
.mode-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(260px, 100%), 1fr)); gap: 12px; }
.mode-card { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; text-align: left; cursor: pointer; font-family: inherit; color: var(--text); background: var(--card); border: 2px solid var(--border); border-radius: var(--radius); padding: 26px 24px; transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease; }
.mode-card:hover { transform: translateY(-3px); box-shadow: var(--shadow); border-color: var(--primary); }
.mode-card:focus-visible { outline: 3px solid var(--primary); outline-offset: 2px; }
.mode-icon { width: 42px; height: 42px; border-radius: 12px; background: var(--primary-50); color: var(--primary); display: flex; align-items: center; justify-content: center; }
.mode-name { font-size: 16px; font-weight: 700; }
.mode-desc { font-size: 13px; color: var(--text-2); line-height: 1.55; }
.mode-hint { color: var(--text-3); font-size: 13px; margin-top: 16px; }
.mode-enter { display: inline-flex; align-items: center; gap: 6px; margin-top: 10px; font-size: 13.5px; font-weight: 700; color: var(--primary); }
@media (prefers-reduced-motion: reduce) { .mode-card { transition: none; } .mode-card:hover { transform: none; } }
</style>
