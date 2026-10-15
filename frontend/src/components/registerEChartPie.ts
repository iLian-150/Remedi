import { use } from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { registerEChartBasics } from './registerEChartBasics'

registerEChartBasics()
use([PieChart])
