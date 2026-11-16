import { use } from 'echarts/core'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

let registered = false

export function registerEChartBasics() {
  if (registered) return
  use([GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])
  registered = true
}
