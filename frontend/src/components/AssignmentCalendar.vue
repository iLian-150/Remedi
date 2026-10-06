<!-- 作业日历（学生/教师双端共用，v0.2.1 新增）
     按作业 created_at（发布日期）打标记：有作业的日期显示圆点，多份显示数量角标。
     点击某天 emit('select', 'yyyy-mm-dd')，父页面据此在下方列出当天发布的作业。 -->
<template>
  <div class="cal">
    <div class="cal-head">
      <button class="icon-btn" title="上个月" @click="move(-1)"><AppIcon name="chevron-left" :size="18" /></button>
      <span class="cal-title">{{ viewYear }} 年 {{ viewMonth + 1 }} 月</span>
      <button class="icon-btn" title="下个月" @click="move(1)"><AppIcon name="chevron-right" :size="18" /></button>
      <button class="btn small cal-today-btn" @click="goToday">回到今天</button>
    </div>
    <div class="cal-grid cal-week">
      <span v-for="w in WEEKDAYS" :key="w">{{ w }}</span>
    </div>
    <div class="cal-grid">
      <button
        v-for="cell in cells"
        :key="cell.date"
        type="button"
        class="cal-cell"
        :class="{ muted: !cell.inMonth, today: cell.date === todayStr, selected: cell.date === selected }"
        @click="$emit('select', cell.date)"
      >
        <span class="cal-daynum tnum">{{ cell.day }}</span>
        <span v-if="marks[cell.date]" class="cal-mark">
          <span class="cal-dot"></span>
          <span v-if="marks[cell.date] > 1" class="cal-count tnum">{{ marks[cell.date] }}</span>
        </span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from './icons/AppIcon.vue'

const props = defineProps<{
  /** yyyy-mm-dd → 当天作业份数 */
  marks: Record<string, number>
  /** 当前选中日期 yyyy-mm-dd（可为空字符串） */
  selected: string
}>()
defineEmits<{ (e: 'select', date: string): void }>()

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

function dateKey(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

const todayStr = dateKey(new Date())
const init = props.selected ? new Date(props.selected + 'T00:00:00') : new Date()
const viewYear = ref(init.getFullYear())
const viewMonth = ref(init.getMonth())

interface CalCell {
  date: string
  day: number
  inMonth: boolean
}

const cells = computed<CalCell[]>(() => {
  const first = new Date(viewYear.value, viewMonth.value, 1)
  // 周一为每周第一天：偏移 = (getDay()+6)%7
  const offset = (first.getDay() + 6) % 7
  const start = new Date(viewYear.value, viewMonth.value, 1 - offset)
  const out: CalCell[] = []
  for (let i = 0; i < 42; i++) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)
    out.push({ date: dateKey(d), day: d.getDate(), inMonth: d.getMonth() === viewMonth.value })
  }
  return out
})

function move(delta: number) {
  const d = new Date(viewYear.value, viewMonth.value + delta, 1)
  viewYear.value = d.getFullYear()
  viewMonth.value = d.getMonth()
}

function goToday() {
  const now = new Date()
  viewYear.value = now.getFullYear()
  viewMonth.value = now.getMonth()
}
</script>

<style scoped>
.cal { max-width: 560px; }
.cal-head { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; }
.cal-title { font-size: 15px; font-weight: 700; min-width: 110px; text-align: center; }
.cal-today-btn { margin-left: auto; }
.cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; }
.cal-week { margin-bottom: 4px; }
.cal-week span { text-align: center; font-size: 12px; color: var(--text-3); padding: 2px 0; }
.cal-cell {
  position: relative;
  border: 1px solid transparent;
  background: transparent;
  border-radius: 8px;
  min-height: 44px;
  padding: 4px 2px 6px;
  cursor: pointer;
  font-family: inherit;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  color: var(--text);
}
.cal-cell:hover { background: var(--bg); }
.cal-cell.muted { color: var(--text-3); }
.cal-cell.today .cal-daynum { color: var(--primary); font-weight: 800; }
.cal-cell.selected { background: var(--primary-50); border-color: var(--primary); }
.cal-daynum { font-size: 13.5px; line-height: 1.2; }
.cal-mark { display: inline-flex; align-items: center; gap: 3px; height: 14px; }
.cal-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--primary); }
.cal-count {
  font-size: 10.5px; font-weight: 700; color: var(--primary);
  background: var(--blue-bg); border-radius: 8px; padding: 0 5px; line-height: 14px;
}
</style>
