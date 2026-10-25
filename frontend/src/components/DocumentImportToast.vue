<template>
  <div v-if="toasts.length" class="document-import-toasts" aria-label="资料导入任务">
    <aside
      v-for="toast in toasts"
      :key="toast.id"
      class="document-import-toast"
      :class="`is-${toast.status}`"
      :role="toast.status === 'error' ? 'alert' : 'status'"
      :aria-live="toast.status === 'error' ? 'assertive' : 'polite'"
      aria-atomic="true"
    >
      <div class="toast-heading">
        <div class="toast-title-group">
          <strong>{{ toast.title }}</strong>
          <small :title="toast.fileName">{{ toast.fileName }}</small>
        </div>
        <span v-if="!toast.canDismiss" class="toast-state">
          {{ toast.percent === null ? '上传中' : `${toast.percent}%` }}
        </span>
        <button v-else class="toast-close" type="button" :disabled="toast.busy" :aria-label="`关闭 ${toast.fileName} 的导入通知`" @click="teacher.dismissKnowledgeImportToast(toast.id)">×</button>
      </div>
      <p v-if="toast.detail" class="toast-detail">{{ toast.detail }}</p>
      <div
        v-if="toast.status !== 'error'"
        class="toast-progress-track"
        role="progressbar"
        :aria-label="`${toast.fileName} ${toast.status === 'uploading' ? '上传' : '导入'}进度`"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-valuenow="toast.percent ?? undefined"
        :aria-valuetext="toast.status === 'waiting' ? '正在确认服务器状态' : undefined"
      >
        <span
          :class="['toast-progress-fill', { indeterminate: toast.percent === null }]"
          :style="toast.percent !== null ? { width: `${toast.percent}%` } : undefined"
        ></span>
      </div>
      <details v-if="toast.warnings.length" class="toast-warnings">
        <summary>{{ toast.warnings.length }} 条处理提示</summary>
        <ul><li v-for="warning in toast.warnings" :key="warning">{{ warning }}</li></ul>
      </details>
      <p v-if="toast.actionError" class="toast-action-error" role="alert">{{ toast.actionError }}</p>
      <button v-if="toast.canRetry && toast.jobId" class="btn ghost small toast-retry" type="button" :disabled="toast.busy" @click="teacher.retryKnowledgeImport(toast.jobId)">{{ toast.busy ? '处理中…' : '重试' }}</button>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useTeacherStore } from '../stores/teacher'

const teacher = useTeacherStore()
const toasts = computed(() => teacher.knowledgeImportToasts)
</script>

<style scoped>
.document-import-toasts { position: fixed; right: 24px; bottom: 24px; z-index: 500; display: flex; width: min(380px, calc(100vw - 32px)); max-height: calc(100dvh - 48px); flex-direction: column; gap: 12px; overflow: auto; padding: 2px; }
.document-import-toast { flex: 0 0 auto; padding: 16px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--card); box-shadow: var(--shadow-lg); animation: knowledge-toast-in .18s ease both; }
.document-import-toast.is-success { border-color: var(--green); }
.document-import-toast.is-error { border-color: var(--red); }
.toast-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.toast-title-group { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
.toast-title-group strong { color: var(--text); font-size: 13px; line-height: 1.45; }
.toast-title-group small { overflow: hidden; color: var(--text-3); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.toast-state { flex: 0 0 auto; color: var(--primary); font-size: 12px; font-variant-numeric: tabular-nums; font-weight: 750; }
.toast-close { display: grid; width: 27px; height: 27px; flex: 0 0 auto; place-items: center; margin: -3px -3px 0 0; border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--text-2); font-size: 21px; line-height: 1; cursor: pointer; }
.toast-close:hover { background: var(--bg); color: var(--text); }
.toast-close:disabled { opacity: .5; cursor: wait; }
.toast-detail { margin: 10px 0 11px; color: var(--text-2); font-size: 12px; line-height: 1.55; overflow-wrap: anywhere; }
.toast-progress-track { position: relative; height: 7px; margin-top: 11px; overflow: hidden; border-radius: 999px; background: var(--gray-bg); }
.toast-progress-fill { display: block; height: 100%; border-radius: inherit; background: var(--primary); transition: width .18s ease; }
.toast-progress-fill.indeterminate { width: 38%; animation: knowledge-progress-sweep 1.35s ease-in-out infinite; }
.is-success .toast-progress-fill { background: var(--green); }
.toast-warnings { margin-top: 11px; color: var(--amber); font-size: 11px; line-height: 1.5; }
.toast-warnings summary { cursor: pointer; }
.toast-warnings ul { display: grid; gap: 5px; max-height: 160px; margin-top: 8px; overflow: auto; padding-left: 17px; }
.toast-action-error { margin-top: 10px; color: var(--red); font-size: 12px; }
.toast-retry { margin-top: 8px; }
@keyframes knowledge-toast-in { from { opacity: 0; transform: translateY(8px) scale(.99); } to { opacity: 1; transform: translateY(0) scale(1); } }
@keyframes knowledge-progress-sweep { from { transform: translateX(-110%); } to { transform: translateX(280%); } }
@media (max-width: 480px) {
  .document-import-toasts { right: 12px; bottom: 12px; width: calc(100vw - 24px); max-height: calc(100dvh - 24px); }
}
@media (prefers-reduced-motion: reduce) {
  .document-import-toast, .toast-progress-fill.indeterminate { animation: none; }
}
</style>
