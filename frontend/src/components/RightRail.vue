<!-- 右侧栏（v0.3.0 首版：便利贴 + 日历 + 当天详情；v0.3.1 改为按页面分工）：
     - mode="notes"（学生端除作业列表页外的所有页面，含主页对话页）：只显示便利贴提醒区。
     - mode="calendar"（学生/教师作业列表页）：只显示日历；点选日期 → 写入对应 store 的
       assignmentDateFilter，作业列表页据此筛选 + 显示当天进度；再次点同一天 = 取消筛选。
     收起/展开由 App.vue 控制（收起态 FAB 图标随场景变：notes=邮件、calendar=日历）。
     数据全部来自现有列表接口前端拼装，不新增后端接口。
     通知唯一来源：教师在教师端一键纠错 → 后端落库 → 这里 GET 拉取展示，学生端不本地伪造。 -->
<template>
  <div class="rail-inner">
    <div class="rail-head">
      <span class="rail-title">
        <AppIcon :name="mode === 'notes' ? 'megaphone' : 'calendar'" :size="17" />
        {{ mode === 'notes' ? '提醒' : '日历' }}
      </span>
      <button class="icon-btn" title="收起右侧栏" @click="$emit('close')">
        <AppIcon name="chevron-right" :size="17" />
      </button>
    </div>

    <!-- 便利贴提醒（仅学生） -->
    <template v-if="mode === 'notes'">
      <div class="rail-sec-head">
        <h3>老师的消息</h3>
        <span v-if="unread > 0" class="badge badge-red">{{ unread }} 条未读</span>
        <button v-if="notes.length && unread > 0" class="text-btn" @click="markAllRead">全部标已读</button>
      </div>
      <div v-if="notes.length" class="notes">
        <div
          v-for="(n, i) in notes"
          :key="n.id"
          class="note-wrap"
          :style="{ '--i': i }"
        >
          <div
            class="note"
            :class="[`note-c${i % 3}`, { read: n.is_read }]"
            :style="{ '--tilt': `${i % 2 === 0 ? -1 : 1}deg`, animationDelay: `${-i * 0.9}s` }"
            @click="openNote(n)"
          >
            <span class="note-tape"></span>
            <p class="note-content">{{ n.content }}</p>
            <span class="note-time">{{ fmtTime(n.created_at) }}</span>
            <span v-if="!n.is_read" class="note-dot" title="未读"></span>
          </div>
        </div>
      </div>
      <p v-else class="hint" style="margin-bottom: 6px">暂无新提醒</p>
    </template>

    <!-- 日历（作业列表页专用）：选中日期与作业列表筛选共用 store 状态 -->
    <template v-else>
      <AssignmentCalendar :marks="marks" :selected="dateFilter" @select="onSelectDay" />
      <p class="hint" style="margin-top: 10px">
        {{ dateFilter ? '已按所选日期筛选作业列表，点「返回查看全部作业」或再点一次该日期可恢复全部。' : '点任意一天，只看当天发布的作业。' }}
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useStudentStore } from '../stores/student'
import { useTeacherStore } from '../stores/teacher'
import type { NotificationItem } from '../api/types'
import AppIcon from './icons/AppIcon.vue'
import AssignmentCalendar from './AssignmentCalendar.vue'

const props = defineProps<{
  /** notes：只显示便利贴提醒；calendar：只显示日历（与作业列表筛选联动） */
  mode: 'notes' | 'calendar'
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'unread-change', count: number): void
}>()

const auth = useAuthStore()
const student = useStudentStore()
const teacher = useTeacherStore()
const router = useRouter()

const isStudent = computed(() => auth.user?.role === 'student')

/** 日历选中日期 = 当前角色 store 的筛选值（单一事实来源，日历与列表双向同步） */
const dateFilter = computed(() =>
  isStudent.value ? student.assignmentDateFilter : teacher.assignmentDateFilter
)

const notes = ref<NotificationItem[]>([])
const unread = ref(0)
/** 日历标记：yyyy-mm-dd → 当天发布的作业份数（仅作业发布，不含提交） */
const marks = ref<Record<string, number>>({})

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

function onSelectDay(date: string) {
  // 再点一次已选中的日期 = 取消筛选
  const next = date === dateFilter.value ? '' : date
  if (isStudent.value) student.setAssignmentDateFilter(next)
  else teacher.setAssignmentDateFilter(next)
}

async function loadNotes() {
  try {
    const res = await student.fetchNotifications()
    notes.value = res.items
    unread.value = res.unread_count
    emit('unread-change', unread.value)
  } catch (e) {
    console.error(e)
  }
}

async function loadMarks() {
  try {
    const m: Record<string, number> = {}
    if (isStudent.value) {
      const list = await student.fetchAssignments()
      for (const a of list) {
        const d = a.created_at.slice(0, 10)
        if (d) m[d] = (m[d] ?? 0) + 1
      }
    } else {
      const list = await teacher.fetchTeacherAssignments()
      for (const a of list) {
        const d = a.created_at.slice(0, 10)
        if (d) m[d] = (m[d] ?? 0) + 1
      }
    }
    marks.value = m
  } catch (e) {
    console.error(e)
  }
}

async function loadForMode() {
  if (!auth.user) return
  if (props.mode === 'notes') {
    if (isStudent.value) await loadNotes()
  } else {
    await loadMarks()
  }
}

// 模式随路由切换（学生主页↔作业列表等），切回来时重新拉数据保证新鲜
watch(() => props.mode, loadForMode)

// 教师在作业列表页发布/删除作业后，日历标记同步刷新
function onAssignmentsChanged() {
  if (props.mode === 'calendar') void loadMarks()
}

onMounted(() => {
  void loadForMode()
  window.addEventListener('assignments-changed', onAssignmentsChanged)
})
onUnmounted(() => window.removeEventListener('assignments-changed', onAssignmentsChanged))

function gotoSubmission(id: number) {
  router.push(`/student/feedback?submission_id=${id}`)
}

async function openNote(n: NotificationItem) {
  if (!n.is_read) {
    try {
      const res = await student.markNotificationsRead([n.id])
      n.is_read = true
      unread.value = res.unread_count
      emit('unread-change', unread.value)
    } catch (e) {
      console.error(e)
    }
  }
  if (n.related_submission_id) gotoSubmission(n.related_submission_id)
}

async function markAllRead() {
  try {
    const res = await student.markNotificationsRead()
    notes.value.forEach((n) => (n.is_read = true))
    unread.value = res.unread_count
    emit('unread-change', unread.value)
  } catch (e) {
    console.error(e)
  }
}
</script>

<style scoped>
.rail-head {
  display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px;
}
.rail-title { display: inline-flex; align-items: center; gap: 7px; font-size: 15.5px; font-weight: 700; }
.rail-sec-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.rail-sec-head h3 { font-size: 14.5px; }
.text-btn {
  margin-left: auto; background: none; border: none; cursor: pointer;
  color: var(--primary); font-size: 12.5px; font-family: var(--font);
}
.text-btn:hover { text-decoration: underline; }

/* ---------- 便利贴 ---------- */
.notes { display: flex; flex-direction: column; gap: 14px; padding-top: 8px; }
.note-wrap { animation: note-in 0.45s cubic-bezier(0.34, 1.4, 0.64, 1) both; animation-delay: calc(var(--i) * 60ms); }
@keyframes note-in {
  from { opacity: 0; transform: translateY(-16px); }
  to { opacity: 1; transform: translateY(0); }
}
.note {
  position: relative; cursor: pointer; border-radius: 4px 4px 10px 4px;
  padding: 16px 13px 10px; box-shadow: 0 3px 8px rgba(15, 23, 42, 0.13);
  transform: rotate(var(--tilt));
  animation: note-sway 6.2s ease-in-out infinite;
  transition: box-shadow 0.25s ease;
}
.note-c0 { background: #fff3b8; }
.note-c1 { background: #ffdce8; }
.note-c2 { background: #d6e9ff; }
.note.read { filter: saturate(0.45); opacity: 0.72; }
.note:hover {
  animation: none;
  transform: rotate(0deg) scale(1.03);
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.2);
}
@keyframes note-sway {
  0%, 100% { transform: rotate(calc(var(--tilt) - 0.6deg)); }
  50% { transform: rotate(calc(var(--tilt) + 0.6deg)); }
}
.note-tape {
  position: absolute; top: -9px; left: 50%;
  transform: translateX(-50%) rotate(-2deg);
  width: 62px; height: 17px; border-radius: 2px;
  background: rgba(255, 255, 255, 0.55);
  border-left: 1px dashed rgba(0, 0, 0, 0.07);
  border-right: 1px dashed rgba(0, 0, 0, 0.07);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}
.note-content { font-size: 13.5px; line-height: 1.55; color: #3f3a2a; }
.note-time { display: block; margin-top: 6px; font-size: 11.5px; color: rgba(63, 58, 42, 0.6); }
.note-dot {
  position: absolute; top: 8px; right: 8px; width: 8px; height: 8px;
  border-radius: 50%; background: var(--red);
}

@media (prefers-reduced-motion: reduce) {
  .note-wrap { animation: none; }
  .note { animation: none; }
  .note:hover { transform: rotate(var(--tilt)); }
}
</style>
