<!-- 品牌 Logo（v0.4.0）：闭环圆弧 + 对勾 —— 象征「诊断 → 修复」的学习闭环。
     入场时圆弧与对勾同步描画、箭头在收尾瞬间于终点弹出落位，
     之后整体做缓慢呼吸（scale 1 ↔ 1.045）。全部 transform/opacity 实现；
     prefers-reduced-motion 时静止展示完整图形。颜色走 currentColor，由父级控制。
     几何校准（2026-10-26）：旧版圆弧两端点与标称半径对不上，实际圆心偏离
     画面中心、箭头两翼全落在圆内且指向与圆周切线相反，看起来整体错位。
     新版按圆心 (24,24)、半径 15 精确计算：圆弧自 20° 顺时针至 330°，
     箭头尖落在圆周上；下翼曾先后与圆弧末端、对勾尖端重叠粘连，已两度
     缩短并下压（188° 方向、长 4.0），对勾长臂同步略收（尖端 29.9,19.9），
     三者互不粘连；对勾按光学中心居中。 -->
<template>
  <svg
    class="brand-logo"
    :width="size"
    :height="size"
    viewBox="0 0 48 48"
    fill="none"
    stroke="currentColor"
    stroke-width="3.2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path class="bl-arc" pathLength="100" d="M38.10 29.13A15 15 0 1 1 36.99 16.50" />
    <path class="bl-arrow" pathLength="100" d="M38.07 10.39 36.99 16.50 33.03 15.94" />
    <path class="bl-check" pathLength="100" d="M17.4 24.2 22.1 28.9 29.9 19.9" />
  </svg>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 40 })
</script>

<style scoped>
.brand-logo {
  flex-shrink: 0;
  animation: bl-breathe 3.8s ease-in-out infinite alternate;
  transform-origin: center;
}
.bl-arc, .bl-check {
  stroke-dasharray: 100;
  stroke-dashoffset: 0;
  animation: bl-draw 1.15s ease-in-out both;
}
.bl-arrow {
  opacity: 0;
  transform-box: fill-box;
  transform-origin: 79% 100%;
  animation: bl-arrow-in 1.15s ease-in-out both;
}
@keyframes bl-draw {
  from { stroke-dashoffset: 100; }
  to { stroke-dashoffset: 0; }
}
@keyframes bl-arrow-in {
  0%, 78% { opacity: 0; transform: scale(.4); }
  92% { opacity: 1; transform: scale(1.08); }
  100% { opacity: 1; transform: scale(1); }
}
@keyframes bl-breathe {
  from { transform: scale(1); }
  to { transform: scale(1.045); }
}
@media (prefers-reduced-motion: reduce) {
  .brand-logo, .bl-arc, .bl-arrow, .bl-check { animation: none; }
  .bl-arrow { opacity: 1; transform: none; }
}
</style>
