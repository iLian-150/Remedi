import { defineAsyncComponent, defineComponent, h } from 'vue'

const ChartPlaceholder = defineComponent({
  name: 'ChartPlaceholder',
  setup() {
    return () => h('div', {
      class: 'chart',
      role: 'status',
      'aria-label': '图表加载中'
    })
  }
})

export default defineAsyncComponent({
  loader: () => import('./EChart.vue'),
  loadingComponent: ChartPlaceholder,
  delay: 0
})
