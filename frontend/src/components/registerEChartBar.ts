import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { registerEChartBasics } from './registerEChartBasics'

registerEChartBasics()
use([BarChart])
