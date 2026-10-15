import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { registerEChartBasics } from './registerEChartBasics'

registerEChartBasics()
use([LineChart])
