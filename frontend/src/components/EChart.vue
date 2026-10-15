<!-- ECharts 共享图表组件：echarts.init + option watcher 封装 -->
<template>
  <div ref="chartRef" class="chart"></div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { init, type ECharts } from 'echarts/core'

const props = defineProps<{
  option: Record<string, unknown>
}>()
const emit = defineEmits<{
  'chart-click': [data: unknown]
}>()

const chartRef = ref<HTMLDivElement | null>(null)
let chart: ECharts | null = null

onMounted(() => {
  if (chartRef.value) {
    chart = init(chartRef.value)
    chart.setOption(props.option)
    chart.on('click', (params: { data?: unknown }) => emit('chart-click', params.data))
    window.addEventListener('resize', handleResize)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
  chart = null
})

watch(
  () => props.option,
  (opt) => {
    chart?.setOption(opt, true)
  },
  { deep: true }
)

function handleResize() {
  chart?.resize()
}
</script>
