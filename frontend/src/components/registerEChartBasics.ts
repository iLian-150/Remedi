import { use } from 'echarts/core'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

let registered = false

export function registerEChartBasics() {
  if (registered) return
  use([GridComponent, TooltipComponent, CanvasRenderer])
  registered = true
}
