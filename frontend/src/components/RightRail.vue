<!-- 右侧栏（v0.3.0）：学生端 = 便利贴提醒区（教师纠错通知） + 日历 + 当天详情；
     教师端 = 日历 + 当天详情（作业可删）。收起/展开由 App.vue 控制（邮件图标入口）。
     数据全部来自现有列表接口前端拼装，不新增后端接口。
     通知唯一来源：教师在教师端一键纠错 → 后端落库 → 这里 GET 拉取展示，学生端不本地伪造。 -->
<template>
  <div class="rail-inner">
    <div class="rail-head">
      <span class="rail-title">
        <AppIcon :name="isStudent ? 'megaphone' : 'calendar'" :size="17" />
        {{ isStudent ? '提醒与日程' : '日程日历' }}
      </span>
      <button class="icon-btn" title="收起右侧栏" @click="$emit('close')">
        <AppIcon name="chevron-right" :size="17" />
      </button>
    </div>

    <!-- 学生：便利贴提醒 -->
    <template v-if="isStudent">
      <div class="rail-sec-head">
        <h3>提醒</h3>
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

    <!-- 日历 -->
    <div class="rail-sec-head" style="margin-top: 18px">
      <h3>日历</h3>
    </div>
    <AssignmentCalendar :marks="marks" :selected="selectedDate" @select="onSelectDay" />

    <!-- 当天详情 -->
    <div class="rail-day">
      <h4>{{ selectedLabel }}</h4>
      <p class="day-group">当天发布的作业</p>
      <div v-if="dayAssignments.length">
        <div v-for="a in dayAssignments" :key="a.id" class="day-item">
          <div class="day-item-main">
            <span class="day-item-title">{{ a.title }}</span>
            <span class="hint">{{ fmtTime(a.created_at) }} 发布 · {{ a.question_count }} 道题</span>
            <span v-if="!isStudent" class="hint">累计提交 {{ a.sub_count }} 人次</span>
          </div>
          <button
            v-if="!isStudent"
            class="icon-btn danger"
            title="删除这份作业"
            @click="removeAssignment(a)"
          >
            <AppIcon name="trash" :size="15" />
          </button>
        </div>
      </div>
      <p v-else class="hint">当天没有发布的作业</p>

      <template v-if="isStudent">
        <p class="day-group">我当天的批改</p>
        <div v-if="daySubmissions.length">
          <button
            v-for="s in daySubmissions"
            :key="s.id"
            class="day-item as-btn"
            @click="gotoSubmission(s.id)"
          >
            <span class="day-item-title">{{ s.question_stem }}</span>
            <span class="hint">
              {{ s.knowledge_point }} ·
              {{ s.error_count > 0 ? `发现 ${s.error_count} 个问题` : '全部正确' }}
            </span>
          </button>
        </div>
        <p v-else class="hint">当天还没有提交记录</p>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useStudentStore } from '../stores/student'
import { useTeacherStore } from '../stores/teacher'
import type { NotificationItem, SubmissionSummary } from '../api/types'
import AppIcon from './icons/AppIcon.vue'
import AssignmentCalendar from './AssignmentCalendar.vue'

/** 右栏内部归一化的作业条目（学生/教师列表接口字段不同，在此抹平；
 *  科目字段两个列表接口都没有，按降级方案不展示科目） */
interface RailAssignment {
  id: number
  title: string
  created_at: string
  question_count: number
  sub_count: number
}

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'unread-change', count: number): void
}>()

const auth = useAuthStore()
const student = useStudentStore()
const teacher = useTeacherStore()
const router = useRouter()

const isStudent = computed(() => auth.user?.role === 'student')

const notes = ref<NotificationItem[]>([])
const unread = ref(0)
const assignments = ref<RailAssignment[]>([])
const mySubs = ref<SubmissionSummary[]>([])

function todayStr(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
const selectedDate = ref(todayStr())
const selectedLabel = computed(() => {
  const [y, m, d] = selectedDate.value.split('-')
  return `${y} 年 ${Number(m)} 月 ${Number(d)} 日`
})

const marks = computed<Record<string, number>>(() => {
  const m: Record<string, number> = {}
  const add = (date: string) => {
    if (date) m[date] = (m[date] ?? 0) + 1
  }
  for (const a of assignments.value) add(a.created_at.slice(0, 10))
  if (isStudent.value) for (const s of mySubs.value) add(s.submitted_at.slice(0, 10))
  return m
})

const dayAssignments = computed(() =>
  assignments.value.filter((a) => a.created_at.slice(0, 10) === selectedDate.value)
)
const daySubmissions = computed(() =>
  mySubs.value.filter((s) => s.submitted_at.slice(0, 10) === selectedDate.value)
)

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

function onSelectDay(date: string) {
  selectedDate.value = date
}

function gotoSubmission(id: number) {
  router.push(`/student/feedback?submission_id=${id}`)
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

async function removeAssignment(a: RailAssignment) {
  if (!window.confirm(`确定删除《${a.title}》吗？删除后学生端将看不到这份作业，已提交的批改记录也会一并删除`)) return
  try {
    await teacher.deleteAssignment(a.id)
    assignments.value = assignments.value.filter((x) => x.id !== a.id)
    window.dispatchEvent(new CustomEvent('assignments-changed'))
  } catch (e) {
    console.error(e)
    window.alert('删除失败，请稍后重试。')
  }
}

onMounted(async () => {
  if (!auth.user) return
  try {
    if (isStudent.value) {
      const [list, subs] = await Promise.all([
        student.fetchAssignments(),
        student.fetchMySubmissions(undefined, 100)
      ])
      assignments.value = list.map((a) => ({
        id: a.id,
        title: a.title,
        created_at: a.created_at,
        question_count: a.question_count,
        sub_count: 0
      }))
      mySubs.value = subs
      await loadNotes()
    } else {
      const list = await teacher.fetchTeacherAssignments()
      assignments.value = list.map((a) => ({
        id: a.id,
        title: a.title,
        created_at: a.created_at,
        question_count: a.questions.length,
        sub_count: a.questions.reduce((sum, q) => sum + q.submission_count, 0)
      }))
    }
  } catch (e) {
    console.error(e)
  }
})
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

/* ---------- 当天详情 ---------- */
.rail-day { margin-top: 16px; }
.rail-day h4 { font-size: 14px; margin-bottom: 8px; }
.day-group { font-size: 12.5px; font-weight: 600; color: var(--text-3); margin: 12px 0 6px; }
.day-item {
  display: flex; align-items: flex-start; gap: 8px; width: 100%;
  background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 9px 11px; margin-bottom: 7px; text-align: left;
}
.day-item.as-btn { cursor: pointer; font-family: var(--font); flex-direction: column; gap: 2px; }
.day-item.as-btn:hover { border-color: var(--primary); }
.day-item-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.day-item-title { font-size: 13.5px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.icon-btn.danger { color: var(--red); }
.icon-btn.danger:hover { background: var(--red-bg); }

@media (prefers-reduced-motion: reduce) {
  .note-wrap { animation: none; }
  .note { animation: none; }
  .note:hover { transform: rotate(var(--tilt)); }
}
</style>
