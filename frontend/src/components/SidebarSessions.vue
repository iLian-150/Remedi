<!-- 左侧栏会话区（v0.6.2 新增，ChatGPT 网页版式）：仅在双端对话页路由下由 App.vue 挂载。
     顶部整宽「新对话」按钮；下方会话列表按更新时间分「今天 / 昨天 / 更早」三组，
     条目只显示标题（单行省略），当前会话高亮，悬停浮现垃圾桶（两段轻确认删除）。
     数据与动作全部走 store 的会话状态层，与对话页共用同一份状态。 -->
<template>
  <section class="sb-sessions">
    <button class="sb-new-btn" :disabled="creating" @click="onCreate">
      <AppIcon name="compose" :size="17" /> 新对话
    </button>

    <div class="sb-list">
      <div v-if="store.sessionsLoading && !store.sessions.length" class="sb-hint">加载中…</div>
      <div v-else-if="store.sessionsError && !store.sessions.length" class="sb-hint sb-error" role="alert">
        <span>{{ store.sessionsError }}</span>
        <button type="button" :disabled="store.sessionsLoading" @click="retrySessions">重试</button>
      </div>
      <div v-else-if="!store.sessions.length" class="sb-hint">还没有历史对话</div>
      <template v-else>
        <div v-if="store.sessionsError" class="sb-hint sb-error" role="alert">
          <span>{{ store.sessionsError }}</span>
          <button type="button" :disabled="store.sessionsLoading" @click="retrySessions">重试</button>
        </div>
        <template v-for="g in groups" :key="g.key">
          <div v-if="g.items.length" class="sb-group-title">{{ g.label }}</div>
          <div
            v-for="s in g.items"
            :key="s.id"
            class="sb-row"
            :class="{ active: s.id === store.activeSessionId, confirming: confirmId === s.id }"
          >
            <template v-if="confirmId === s.id">
              <span class="sb-confirm-text">确认删除？</span>
              <button class="sb-confirm-yes" @click="onRemove(s.id)">删除</button>
              <button class="sb-confirm-no" @click="confirmId = null">取消</button>
            </template>
            <template v-else>
              <button class="sb-main" :title="s.title" @click="onSelect(s.id)">
                <span class="sb-title">{{ s.title }}</span>
              </button>
              <button class="sb-trash" title="删除这条对话" @click="confirmId = s.id">
                <AppIcon name="trash" :size="15" />
              </button>
            </template>
          </div>
        </template>
        <div v-if="store.sessionsPageError" class="sb-page-error" role="alert">
          {{ store.sessionsPageError }}
        </div>
        <button
          v-if="store.sessionsHasMore || store.sessionsPageLoading || store.sessionsPageError"
          class="sb-load-more"
          :disabled="store.sessionsPageLoading"
          @click="store.loadMoreSessions()"
        >
          {{ store.sessionsPageLoading ? '加载中…' : store.sessionsPageError ? '重试加载' : '加载更早对话' }}
        </button>
      </template>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useStudentStore } from '../stores/student'
import { useTeacherStore } from '../stores/teacher'
import type { ChatSession } from '../api/types'
import AppIcon from './icons/AppIcon.vue'

const emit = defineEmits<{ (e: 'navigate'): void }>()

const auth = useAuthStore()
// 双端 store 的会话状态层结构一致，按角色取当前端的那份
const store = computed(() =>
  auth.role === 'teacher' ? useTeacherStore() : useStudentStore()
)

const confirmId = ref<number | null>(null)
const creating = ref(false)

onMounted(() => {
  store.value.loadSessions()
})

async function retrySessions() {
  await store.value.loadSessions(true)
}

type GroupKey = 'today' | 'yesterday' | 'earlier'
function groupOf(iso: string): GroupKey {
  const t = new Date(iso.replace(' ', 'T')).getTime()
  if (Number.isNaN(t)) return 'earlier'
  const d = new Date(t)
  const startOfDay = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const days = Math.round((startOfDay(new Date()) - startOfDay(d)) / 86400000)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  return 'earlier'
}

const groups = computed<{ key: GroupKey; label: string; items: ChatSession[] }[]>(() => {
  const itemsByGroup: Record<GroupKey, ChatSession[]> = {
    today: [],
    yesterday: [],
    earlier: []
  }
  for (const session of store.value.sessions) {
    itemsByGroup[groupOf(session.updated_at)].push(session)
  }
  return [
    { key: 'today', label: '今天', items: itemsByGroup.today },
    { key: 'yesterday', label: '昨天', items: itemsByGroup.yesterday },
    { key: 'earlier', label: '更早', items: itemsByGroup.earlier }
  ]
})

async function onCreate() {
  if (creating.value) return
  creating.value = true
  try {
    await store.value.startSidebarSession()
    confirmId.value = null
    emit('navigate')
  } catch (e) {
    console.error(e)
  } finally {
    creating.value = false
  }
}

function onSelect(id: number) {
  confirmId.value = null
  store.value.selectSidebarSession(id)
  emit('navigate')
}

async function onRemove(id: number) {
  try {
    await store.value.removeSidebarSession(id)
  } catch (e) {
    console.error(e)
  } finally {
    confirmId.value = null
  }
}
</script>

<style scoped>
.sb-sessions {
  border-top: 1px solid var(--border);
  margin-top: 14px; padding-top: 14px;
  flex: 1; min-height: 0;
  display: flex; flex-direction: column;
}
.sb-new-btn {
  width: 100%; display: flex; align-items: center; gap: 8px;
  padding: 9px 12px; margin-bottom: 10px; flex-shrink: 0;
  background: var(--card); color: var(--text);
  border: 1px solid var(--border); border-radius: 10px;
  font-size: 14px; font-weight: 600; font-family: var(--font); cursor: pointer;
  transition: background 0.2s ease, border-color 0.2s ease, transform 0.2s ease;
}
.sb-new-btn:hover:not(:disabled) { background: var(--bg); border-color: #C9D6F2; }
.sb-new-btn:active:not(:disabled) { transform: scale(0.99); }
.sb-new-btn:disabled { opacity: 0.6; cursor: wait; }
.sb-new-btn .app-icon { color: var(--primary); }
.sb-list { flex: 1; min-height: 0; overflow-y: auto; padding-right: 2px; }
.sb-hint { font-size: 13px; color: var(--text-3); padding: 10px 10px 4px; }
.sb-page-error { padding: 8px 10px 2px; color: var(--red); font-size: 12px; }
.sb-load-more {
  width: calc(100% - 12px); margin: 8px 6px 10px; padding: 7px 9px;
  border: 1px solid var(--border); border-radius: 8px; background: var(--card);
  color: var(--primary); font: 12px var(--font); cursor: pointer;
}
.sb-load-more:disabled { opacity: 0.6; cursor: wait; }
.sb-error { display: flex; align-items: center; gap: 8px; color: var(--red); }
.sb-error span { min-width: 0; }
.sb-error button { flex-shrink: 0; padding: 2px 6px; border: 1px solid var(--border); border-radius: 6px; background: var(--card); color: var(--primary); font: inherit; cursor: pointer; }
.sb-error button:disabled { opacity: 0.6; cursor: wait; }
.sb-group-title {
  font-size: 11px; font-weight: 700; letter-spacing: 0.6px; color: var(--text-3);
  padding: 10px 10px 4px;
}
.sb-group-title:first-child { padding-top: 2px; }
.sb-row {
  display: flex; align-items: center; gap: 4px;
  border-radius: 9px; padding: 2px 4px 2px 2px;
}
.sb-row:hover { background: var(--bg); }
.sb-row.active { background: var(--primary-50); }
.sb-row.confirming { background: var(--red-bg); padding: 6px 8px; }
.sb-main {
  flex: 1; min-width: 0; text-align: left; background: none; border: none; cursor: pointer;
  font-family: var(--font); color: var(--text);
  padding: 6px 8px; border-radius: 7px;
}
.sb-title {
  display: block; font-size: 13.5px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sb-row.active .sb-title { color: var(--primary); font-weight: 600; }
.sb-trash {
  flex-shrink: 0; background: transparent; border: none; cursor: pointer;
  color: var(--text-3); display: inline-flex; align-items: center; justify-content: center;
  padding: 5px; border-radius: 7px;
  opacity: 0; transition: opacity 0.18s ease, color 0.18s ease, background 0.18s ease;
}
.sb-row:hover .sb-trash, .sb-row.active .sb-trash, .sb-row:focus-within .sb-trash { opacity: 1; }
.sb-trash:hover { color: var(--red); background: #fff; }
.sb-confirm-text { flex: 1; font-size: 12.5px; font-weight: 600; color: #991B1B; white-space: nowrap; }
.sb-confirm-yes {
  flex-shrink: 0; border: none; background: var(--red); color: #fff; cursor: pointer;
  border-radius: 7px; padding: 4px 9px; font-size: 12px; font-weight: 600; font-family: var(--font);
}
.sb-confirm-no {
  flex-shrink: 0; border: 1px solid var(--border); background: #fff; color: var(--text-2); cursor: pointer;
  border-radius: 7px; padding: 4px 9px; font-size: 12px; font-family: var(--font);
}
@media (prefers-reduced-motion: reduce) {
  .sb-new-btn, .sb-trash { transition: none; }
}
</style>
