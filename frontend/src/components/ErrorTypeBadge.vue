<!-- 错因三色徽标：计算失误=琥珀 / 概念混淆=红 / 审题遗漏=紫 / 无法解析=灰 -->
<template>
  <span :class="errorTypeBadgeClass(type)">{{ type }}</span>
</template>

<script setup lang="ts">
import { errorTypeBadgeClass } from '../utils/errorType'

defineProps<{ type: string }>()
</script>
