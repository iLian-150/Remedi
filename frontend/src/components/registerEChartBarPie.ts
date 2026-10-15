import { use } from 'echarts/core'
import { BarChart, PieChart } from 'echarts/charts'
import { registerEChartBasics } from './registerEChartBasics'

registerEChartBasics()
use([BarChart, PieChart])
