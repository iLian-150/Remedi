<!-- 历史对话面板（v0.6.0 新增，双端共用）：参考 Muse 式会话列表——
     干净的列表行：标题 + 相对时间，当前会话高亮；顶部「+ 新对话」；
     每行右侧垃圾桶可单独删除（点一次变「确认删除？」轻确认，再点才删）。
     本组件只管呈现与事件分发，数据由对话页经 store 拉取后传入。 -->
<template>
  <div class="session-panel" :class="`session-panel-${variant}`" :role="variant === 'sidebar' ? 'region' : 'dialog'" aria-label="历史对话">
    <div v-if="variant === 'popover'" class="session-panel-head">
      <span class="session-panel-title"><AppIcon name="history" :size="16" /> 历史对话</span>
      <button class="icon-btn" title="关闭" @click="emit('close')">
        <AppIcon name="x" :size="16" />
      </button>
    </div>
    <button class="session-new-btn" @click="emit('create')">
      <AppIcon name="plus" :size="15" /> 新对话
    </button>
    <slot v-if="variant === 'sidebar'" name="navigation" />
    <div v-if="variant === 'sidebar'" class="session-panel-head">
      <span class="session-panel-title"><AppIcon name="history" :size="16" /> 历史对话</span>
    </div>
    <div v-if="loading" class="session-empty">加载中…</div>
    <div v-else-if="!sessions.length" class="session-empty">还没有历史对话，先开始聊聊吧。</div>
    <div v-else class="session-list">
      <div
        v-for="s in sessions"
        :key="s.id"
        class="session-row"
        :class="{ active: s.id === currentId, confirming: confirmId === s.id }"
      >
        <button class="session-main" @click="emit('select', s)">
          <span class="session-title">{{ s.title }}</span>
          <span class="session-meta">
            {{ relativeTime(s.updated_at) }}
          </span>
        </button>
        <template v-if="confirmId === s.id">
          <button class="session-confirm-yes" @click="emit('remove', s)">确认删除</button>
          <button class="session-confirm-no" @click="confirmId = null">取消</button>
        </template>
        <button
          v-else
          class="icon-btn session-trash"
          title="删除这条对话"
          @click="confirmId = s.id"
        >
          <AppIcon name="trash" :size="15" />
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { ChatSession } from '../api/types'
import AppIcon from './icons/AppIcon.vue'

withDefaults(defineProps<{
  sessions: ChatSession[]
  currentId: number | null
  loading: boolean
  variant?: 'popover' | 'sidebar'
}>(), { variant: 'popover' })

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'create'): void
  (e: 'select', s: ChatSession): void
  (e: 'remove', s: ChatSession): void
}>()

const confirmId = ref<number | null>(null)

/** 相对时间：刚刚 / N 分钟前 / N 小时前 / 昨天 / N 天前 / 日期 */
function relativeTime(iso: string): string {
  const t = new Date(iso.replace(' ', 'T')).getTime()
  if (Number.isNaN(t)) return ''
  const diff = Date.now() - t
  const minute = 60 * 1000
  const hour = 60 * minute
  const day = 24 * hour
  if (diff < minute) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 2 * day) return '昨天'
  if (diff < 30 * day) return `${Math.floor(diff / day)} 天前`
  return iso.replace('T', ' ').slice(0, 10)
}
</script>

<style scoped>
.session-panel {
  position: absolute; top: calc(100% + 8px); right: 0; z-index: 40;
  width: min(360px, calc(100vw - 32px));
  background: var(--card); border: 1px solid #E4E9F2; border-radius: 14px;
  box-shadow: 0 16px 40px rgba(15, 23, 42, 0.16);
  padding: 12px; animation: session-pop 0.18s ease both;
}
.session-panel-sidebar {
  position: relative;
  top: auto;
  right: auto;
  z-index: auto;
  display: flex;
  width: 100%;
  min-height: 0;
  flex: 1 1 auto;
  flex-direction: column;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  animation: none;
}
.session-panel-sidebar .session-panel-head { padding: 14px 20px 10px; }
.session-panel-sidebar .session-new-btn { width: auto; margin: 0 14px 12px; padding: 9px 12px; border-style: solid; }
.session-panel-sidebar .session-list { min-height: 0; max-height: none; flex: 1 1 auto; padding: 0 10px 12px; }
.session-panel-sidebar .session-empty { padding: 20px 16px; }
@keyframes session-pop {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
.session-panel-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 2px 4px 10px;
}
.session-panel-title { display: inline-flex; align-items: center; gap: 7px; font-size: 14.5px; font-weight: 700; }
.session-new-btn {
  width: 100%; display: flex; align-items: center; justify-content: center; gap: 6px;
  border: 1px dashed #B7C9F5; background: var(--primary-50); color: var(--primary);
  border-radius: 10px; padding: 9px 0; font-size: 13.5px; font-weight: 600;
  cursor: pointer; font-family: var(--font); margin-bottom: 8px;
  transition: background 0.2s ease, border-color 0.2s ease;
}
.session-new-btn:hover { background: #EAF1FE; border-color: var(--primary); }
.session-empty { padding: 18px 6px; text-align: center; font-size: 13.5px; color: var(--text-2); }
.session-list { max-height: 46vh; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
.session-row {
  display: flex; align-items: center; gap: 6px;
  border-radius: 10px; padding: 4px 6px 4px 4px;
}
.session-row:hover { background: #F8FAFF; }
.session-row.active { background: var(--primary-50); }
.session-row.confirming { background: var(--red-bg); }
.session-main {
  flex: 1; min-width: 0; text-align: left; background: none; border: none; cursor: pointer;
  font-family: var(--font); color: var(--text); padding: 6px 8px; border-radius: 8px;
  display: flex; flex-direction: column; gap: 2px;
}
.session-title {
  font-size: 14px; font-weight: 600;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.session-row.active .session-title { color: var(--primary); }
.session-meta { font-size: 12px; color: var(--text-3); }
.session-trash { color: var(--text-3); flex-shrink: 0; }
.session-trash:hover { color: var(--red); }
.session-confirm-yes {
  flex-shrink: 0; border: none; background: var(--red); color: #fff; cursor: pointer;
  border-radius: 8px; padding: 6px 10px; font-size: 12.5px; font-weight: 600; font-family: var(--font);
}
.session-confirm-no {
  flex-shrink: 0; border: 1px solid var(--border); background: #fff; color: var(--text-2); cursor: pointer;
  border-radius: 8px; padding: 6px 10px; font-size: 12.5px; font-family: var(--font);
}
@media (prefers-reduced-motion: reduce) {
  .session-panel { animation: none; }
  .session-new-btn { transition: none; }
}
</style>
