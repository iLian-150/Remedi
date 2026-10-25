<template>
  <aside
    v-if="toast"
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
      <span v-if="toast.status === 'uploading'" class="toast-state">
        {{ toast.percent === null ? '上传中' : `${toast.percent}%` }}
      </span>
      <span v-else-if="toast.status === 'processing'" class="toast-state">处理中</span>
      <button v-else class="toast-close" type="button" aria-label="关闭导入通知" @click="teacher.dismissKnowledgeImportToast">×</button>
    </div>
    <p v-if="toast.detail" class="toast-detail">{{ toast.detail }}</p>
    <div
      v-if="toast.status !== 'error'"
      class="toast-progress-track"
      role="progressbar"
      :aria-label="toast.status === 'processing' ? '正在建立检索索引' : '资料导入进度'"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-valuenow="toast.status === 'success' ? 100 : toast.status === 'uploading' ? toast.percent ?? undefined : undefined"
      :aria-valuetext="toast.status === 'processing' ? '文件已上传，正在建立检索索引' : undefined"
    >
      <span
        :class="['toast-progress-fill', { indeterminate: toast.status === 'processing' || (toast.status === 'uploading' && toast.percent === null) }]"
        :style="toast.status === 'success' ? { width: '100%' } : toast.status === 'uploading' && toast.percent !== null ? { width: `${toast.percent}%` } : undefined"
      ></span>
    </div>
    <ul v-if="toast.warnings.length" class="toast-warnings">
      <li v-for="warning in toast.warnings" :key="warning">{{ warning }}</li>
    </ul>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useTeacherStore } from '../stores/teacher'

const teacher = useTeacherStore()
const toast = computed(() => teacher.knowledgeImportToast)
</script>

<style scoped>
.document-import-toast { position: fixed; right: 24px; bottom: 24px; z-index: 500; width: min(380px, calc(100vw - 32px)); padding: 16px; border: 1px solid #DCE5F4; border-radius: 14px; background: #fff; box-shadow: 0 18px 48px rgba(20, 35, 64, .2); animation: knowledge-toast-in .18s ease both; }
.document-import-toast.is-success { border-color: #BFE7D2; }
.document-import-toast.is-error { border-color: #F0C6C3; }
.toast-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.toast-title-group { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
.toast-title-group strong { color: var(--text); font-size: 13px; line-height: 1.45; }
.toast-title-group small { overflow: hidden; color: var(--text-3); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.toast-state { flex: 0 0 auto; color: var(--primary); font-size: 12px; font-variant-numeric: tabular-nums; font-weight: 750; }
.is-success .toast-state { color: #16845C; }
.is-error .toast-state { color: #B42318; }
.toast-close { display: grid; width: 27px; height: 27px; flex: 0 0 auto; place-items: center; margin: -3px -3px 0 0; border: 0; border-radius: 7px; background: transparent; color: #64748B; font-size: 21px; line-height: 1; cursor: pointer; }
.toast-close:hover { background: #F1F4F8; color: var(--text); }
.toast-detail { margin: 10px 0 11px; color: var(--text-2); font-size: 12px; line-height: 1.55; overflow-wrap: anywhere; }
.toast-progress-track { position: relative; height: 7px; overflow: hidden; border-radius: 999px; background: #E8EDF6; }
.toast-progress-fill { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #3475F6, #2453D9); transition: width .18s ease; }
.toast-progress-fill.indeterminate { width: 38%; animation: knowledge-progress-sweep 1.35s ease-in-out infinite; }
.is-success .toast-progress-fill { background: linear-gradient(90deg, #27AE78, #16845C); }
.toast-warnings { display: grid; gap: 5px; margin: 11px 0 0; padding-left: 17px; color: #9A5B11; font-size: 11px; line-height: 1.5; }
@keyframes knowledge-toast-in { from { opacity: 0; transform: translateY(8px) scale(.99); } to { opacity: 1; transform: translateY(0) scale(1); } }
@keyframes knowledge-progress-sweep { from { transform: translateX(-110%); } to { transform: translateX(280%); } }
@media (max-width: 480px) {
  .document-import-toast { right: 12px; bottom: 12px; width: calc(100vw - 24px); }
}
@media (prefers-reduced-motion: reduce) {
  .document-import-toast, .toast-progress-fill.indeterminate { animation: none; }
}
</style>
