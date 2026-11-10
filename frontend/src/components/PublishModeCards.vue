<template>
  <div class="mode-grid">
    <button type="button" class="mode-card" @click="$emit('choose', 'online')">
      <span class="mode-icon"><AppIcon name="edit" :size="22" /></span>
      <span class="mode-name">线上作业</span>
      <span class="mode-desc">逐题录入或拍照识题，学生在线作答</span>
      <span class="mode-enter">发布线上作业 <AppIcon name="arrow-right" :size="15" /></span>
    </button>
    <button type="button" class="mode-card" @click="$emit('choose', 'offline')">
      <span class="mode-icon"><AppIcon name="book" :size="22" /></span>
      <span class="mode-name">线下作业 · 练习册</span>
      <span class="mode-desc">选择练习册与页码，识别后由学生拍照提交</span>
      <span class="mode-enter">发布练习册作业 <AppIcon name="arrow-right" :size="15" /></span>
    </button>
  </div>
</template>
<script setup lang="ts">
import AppIcon from './icons/AppIcon.vue'
defineEmits<{ choose: [mode: 'online' | 'offline'] }>()
</script>
<style scoped>
.mode-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(260px, 100%), 1fr)); gap: 12px; }
.mode-card { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; text-align: left; cursor: pointer; font-family: inherit; color: var(--text); background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-control); padding: 26px 24px; transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease; }
.mode-card:hover { transform: translateY(-3px); box-shadow: var(--shadow); border-color: var(--primary); }
.mode-card:focus-visible { outline: 3px solid var(--primary); outline-offset: 2px; }
.mode-icon { width: 42px; height: 42px; border-radius: var(--radius-control); background: var(--primary-50); color: var(--primary); display: flex; align-items: center; justify-content: center; }
.mode-name { font-size: 16px; font-weight: 700; }
.mode-desc { font-size: 13px; color: var(--text-2); line-height: 1.55; }
.mode-enter { display: inline-flex; align-items: center; gap: 6px; margin-top: auto; padding-top: 8px; font-size: 13px; font-weight: 700; color: var(--primary); }
@media (prefers-reduced-motion: reduce) { .mode-card { transition: none; } .mode-card:hover { transform: none; } }
</style>
