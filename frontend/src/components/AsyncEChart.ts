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

function createAsyncChart(register: () => Promise<unknown>) {
  return defineAsyncComponent({
    loader: async () => {
      const component = import('./EChart.vue')
      await Promise.all([register(), component])
      return component
    },
    loadingComponent: ChartPlaceholder,
    delay: 0
  })
}

export const AsyncEChartBar = createAsyncChart(() => import('./registerEChartBar'))
export const AsyncEChartPie = createAsyncChart(() => import('./registerEChartPie'))
export const AsyncEChartLine = createAsyncChart(() => import('./registerEChartLine'))
export const AsyncEChartBarPie = createAsyncChart(() => import('./registerEChartBarPie'))
