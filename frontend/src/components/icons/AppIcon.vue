<!-- 线性 SVG 图标组件（路径库见 ./paths.ts）。
     用法：<AppIcon name="camera" :size="20" />
     全站图标统一从这里取，禁止再使用 emoji 充当图标。 -->
<template>
  <svg
    class="app-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    v-html="ICON_PATHS[name]"
  />
</template>

<script setup lang="ts">
import { ICON_PATHS, type IconName } from './paths'

withDefaults(defineProps<{ name: IconName; size?: number }>(), { size: 20 })
</script>

<style scoped>
.app-icon {
  flex-shrink: 0;
  vertical-align: middle;
}
</style>
