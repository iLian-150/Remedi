<!-- 教师端：作业管理（v0.2.0 新增）
     数据源：GET /api/teacher/assignments（4.8），含每题提交人数。
     v0.2.1 曾在页内放作业日历；v0.3.0 日历迁至右侧栏；v0.3.1 日历只在本页右栏出现，
     点选日期 → store.assignmentDateFilter 生效 → 本页按发布日期筛选，「返回查看全部作业」清除；
     v0.3.0 新增删除已发布作业（二次确认，后端级联删除学生提交数据）。 -->
<template>
  <div class="page">
    <div class="page-head"><h2>作业</h2></div>

    <section class="card publish-launch">
      <div class="publish-launch-head">
        <h3>发布作业</h3>
        <button class="btn small inline-icon" :aria-expanded="publishOpen" @click="togglePublish">
          <AppIcon :name="publishOpen ? 'chevron-down' : 'plus'" :size="15" />
          {{ publishOpen ? '收起' : '开始发布' }}
        </button>
      </div>
      <component
        :is="EmbeddedPublish"
        v-if="publishReady"
        v-show="publishOpen"
        :embedded="true"
        @published="onPublished"
      />
    </section>

    <section class="assignment-management">
      <div class="management-heading">
        <h3>作业管理</h3>
        <span>最新发布在前</span>
      </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="toast" class="ok-msg">{{ toast }}</div>
    <div v-if="loading" class="loading">作业加载中…</div>

    <template v-if="!loading">
      <p class="rail-note"><AppIcon name="calendar" :size="15" /> 可用右侧日历筛选发布日期。</p>

      <!-- 日期筛选状态栏（右侧栏日历选中某天时出现） -->
      <div v-if="dateFilter" class="filter-bar">
        <span class="filter-title">{{ dateFilterLabel }} 发布的作业 · 共 {{ assignments.length }} 份</span>
        <button class="btn secondary small" @click="clearFilter">返回查看全部作业</button>
      </div>

      <!-- 作业（全部或按所选日期筛选后） -->
      <div v-for="a in assignments" :key="a.id" class="card">
        <div class="card-head-row">
          <div>
            <h3>
              {{ a.title }}
              <span v-if="a.mode === 'offline'" class="badge badge-amber" style="margin-left: 6px">线下练习</span>
            </h3>
            <p class="card-sub" style="margin-bottom: 0">
              {{ fmtTime(a.created_at) }} 发布 · 共 {{ a.questions.length }} 题
              <template v-if="a.mode === 'offline'">
                <template v-if="a.workbook_title"> · {{ a.workbook_title }}</template>
                <template v-if="a.page_range"> · {{ a.page_range }}</template>
                <template v-if="a.deadline"> · 截止 {{ fmtTime(a.deadline) }}</template>
              </template>
            </p>
          </div>
          <div class="head-actions">
            <button class="btn small secondary inline-icon" :disabled="remindingId === a.id" @click="remind(a)">
              <AppIcon name="megaphone" :size="15" /> {{ remindingId === a.id ? '提醒中…' : '提醒未交' }}
            </button>
            <button v-if="a.can_delete" class="btn small danger-outline inline-icon" @click="askDelete(a)">
              <AppIcon name="trash" :size="15" /> 删除
            </button>
          </div>
        </div>
        <table class="table">
          <thead>
            <tr><th style="width: 72px">题型</th><th>题干</th><th style="width: 130px">知识点</th><th style="width: 96px">已提交</th></tr>
          </thead>
          <tbody>
            <tr v-for="q in a.questions" :key="q.id">
              <td>
                <span class="badge" :class="q.subject === 'math' ? 'badge-blue' : 'badge-gray'">{{ subjectLabel(q.subject) }}</span>
              </td>
              <td>{{ q.prompt }}</td>
              <td>{{ q.knowledge_point }}</td>
              <td class="num tnum">{{ q.submission_count }} 人</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="!assignments.length && dateFilter" class="card">
        <div class="empty">这一天没有发布的作业，点上方「返回查看全部作业」看全部。</div>
      </div>

      <div v-if="!assignments.length && !dateFilter" class="card">
        <div class="empty">还没有发布过作业，可在上方发布新作业。</div>
      </div>
    </template>

    </section>

    <!-- 删除二次确认 -->
    <div v-if="pendingDelete" class="modal-mask" @click.self="pendingDelete = null">
      <div class="modal">
        <h3>删除作业</h3>
        <p style="margin: 10px 0 4px">确定删除《{{ pendingDelete.title }}》吗？</p>
        <p class="hint">删除后学生端将看不到这份作业，已提交的批改记录也会一并删除</p>
        <div v-if="deleteError" class="error-msg" style="margin-top: 10px">{{ deleteError }}</div>
        <div class="toolbar" style="margin: 16px 0 0; justify-content: flex-end">
          <button class="btn secondary" :disabled="deleting" @click="pendingDelete = null">取消</button>
          <button class="btn danger" :disabled="deleting" @click="confirmDelete">
            {{ deleting ? '删除中…' : '确认删除' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTeacherStore } from '../../stores/teacher'
import type { TeacherAssignment } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'

const teacher = useTeacherStore()
const route = useRoute()
const router = useRouter()
const EmbeddedPublish = defineAsyncComponent(() => import('./TeacherPublish.vue'))
const publishOpen = ref(route.query.publish === '1')
const publishReady = ref(publishOpen.value)
const assignments = ref<TeacherAssignment[]>([])
const loading = ref(false)
const error = ref('')
const toast = ref('')
const pendingDelete = ref<TeacherAssignment | null>(null)
const deleting = ref(false)
const deleteError = ref('')

function togglePublish() {
  publishOpen.value = !publishOpen.value
  if (publishOpen.value) {
    publishReady.value = true
    void router.replace({ path: '/teacher/assignments', query: { publish: '1' } })
  } else {
    void router.replace({ path: '/teacher/assignments', query: {} })
  }
}

async function onPublished() {
  publishOpen.value = false
  publishReady.value = false
  toast.value = '作业已发布。'
  void router.replace({ path: '/teacher/assignments', query: {} })
  if (dateFilter.value) teacher.setAssignmentDateFilter('')
  try {
    await reload()
    window.dispatchEvent(new CustomEvent('assignments-changed', {
      detail: { assignments: assignments.value }
    }))
  } catch (e) {
    console.error(e)
  }
  setTimeout(() => (toast.value = ''), 4000)
}

function subjectLabel(subject: string): string {
  const labels: Record<string, string> = {
    math: '数学', english: '英语', english_exercise: '英语练习', physics: '物理',
    chemistry: '化学', biology: '生物', chinese: '语文', history: '历史',
    geography: '地理', politics: '道德与法治', computer_science: '信息科技',
    art: '艺术', music: '音乐', pe: '体育', other: '其他',
  }
  return labels[subject] ?? '其他'
}

/** 右侧栏日历选中的发布日期（yyyy-mm-dd，空 = 不筛选）——与日历共用 store 状态 */
const dateFilter = computed(() => teacher.assignmentDateFilter)

watch(dateFilter, () => {
  void reload().catch((e) => console.error(e))
})

const dateFilterLabel = computed(() => {
  if (!dateFilter.value) return ''
  const [y, m, d] = dateFilter.value.split('-')
  return `${y} 年 ${Number(m)} 月 ${Number(d)} 日`
})

function clearFilter() {
  teacher.setAssignmentDateFilter('')
}

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

let assignmentLoadGeneration = 0

function sortByPublishedTime(list: TeacherAssignment[]) {
  return [...list].sort((a, b) =>
    b.created_at.localeCompare(a.created_at) || b.id - a.id
  )
}

async function reload() {
  const generation = ++assignmentLoadGeneration
  loading.value = true
  error.value = ''
  try {
    const list = await teacher.fetchTeacherAssignments(dateFilter.value || undefined)
    if (generation === assignmentLoadGeneration) assignments.value = sortByPublishedTime(list)
  } catch (e) {
    if (generation === assignmentLoadGeneration) {
      error.value = '作业列表加载失败，请确认后端已启动。'
    }
    throw e
  } finally {
    if (generation === assignmentLoadGeneration) loading.value = false
  }
}

function askDelete(a: TeacherAssignment) {
  deleteError.value = ''
  pendingDelete.value = a
}

// ---------- 一键提醒未交学生（v0.5.0）：只提醒还没提交全部题目的学生 ----------
const remindingId = ref<number | null>(null)

async function remind(a: TeacherAssignment) {
  if (remindingId.value !== null) return
  remindingId.value = a.id
  try {
    const n = await teacher.remindAssignment(a.id)
    toast.value = n > 0 ? `已提醒 ${n} 位学生` : '全班都交齐了，没有需要提醒的学生。'
    setTimeout(() => (toast.value = ''), 4000)
  } catch (e) {
    error.value = '提醒发送失败，请稍后重试。'
    console.error(e)
  } finally {
    remindingId.value = null
  }
}

async function confirmDelete() {
  if (!pendingDelete.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    const target = pendingDelete.value
    await teacher.deleteAssignment(target.id)
    assignments.value = assignments.value.filter((x) => x.id !== target.id)
    pendingDelete.value = null
    toast.value = `已删除《${target.title}》，学生端已同步移除。`
    // 通知右侧栏日历刷新（右侧栏删除时也会发同一事件让本页刷新）
    window.dispatchEvent(new CustomEvent('assignments-changed', {
      detail: { assignments: assignments.value }
    }))
    setTimeout(() => (toast.value = ''), 4000)
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    deleteError.value = typeof detail === 'string' ? `删除失败：${detail}` : '删除失败，请稍后重试。'
    console.error(e)
  } finally {
    deleting.value = false
  }
}

// 右侧栏里删除作业后，本页同步刷新
async function onAssignmentsChanged(event: Event) {
  const updated = (event as CustomEvent<{ assignments?: TeacherAssignment[] }>).detail?.assignments
  if (Array.isArray(updated)) {
    assignments.value = sortByPublishedTime(updated)
    return
  }
  try {
    await reload()
  } catch (e) {
    console.error(e)
  }
}

onMounted(() => {
  void reload().catch((e) => console.error(e))
  window.addEventListener('assignments-changed', onAssignmentsChanged)
})
onUnmounted(() => window.removeEventListener('assignments-changed', onAssignmentsChanged))
</script>

<style scoped>
.rail-note {
  display: flex; align-items: center; gap: 7px;
  font-size: 13.5px; color: var(--text-2);
  background: var(--primary-50); border: 1px solid #DBEAFE; border-radius: 10px;
  padding: 10px 14px; margin-bottom: 16px;
}
.publish-launch { padding: 16px 20px; }
.publish-launch-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.publish-launch-head h3 { margin: 0; }
.assignment-management { margin-top: 24px; }
.management-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.management-heading h3 { font-size: 18px; }
.management-heading span { color: var(--text-3); font-size: 13px; }
.card-head-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.head-actions { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
.filter-bar {
  display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;
  background: var(--primary-50); border: 1px solid #DBEAFE; border-radius: 12px;
  padding: 12px 16px; margin-bottom: 16px;
}
.filter-title { font-size: 14.5px; font-weight: 700; }
.btn.danger-outline {
  background: #fff; color: var(--red); border: 1px solid #FECACA;
}
.btn.danger-outline:hover { background: var(--red-bg); }
.btn.danger { background: var(--red); border-color: var(--red); color: #fff; }
.btn.danger:hover { background: #B91C1C; }
.modal-mask {
  position: fixed; inset: 0; z-index: 300;
  background: rgba(15, 23, 42, 0.4);
  display: flex; align-items: center; justify-content: center; padding: 20px;
}
.modal {
  background: var(--card); border-radius: 14px; box-shadow: var(--shadow);
  padding: 22px 24px; width: min(440px, 100%);
}
.modal h3 { font-size: 16.5px; }
</style>
