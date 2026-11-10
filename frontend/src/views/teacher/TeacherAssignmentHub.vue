<template>
  <div class="page assignment-hub">
    <div class="assignment-entry-grid">
      <section class="card publish-entry">
        <h2 class="entry-heading">发布作业</h2>
        <PublishModeCards @choose="openPublish" />
      </section>

      <router-link to="/teacher/assignments/manage" class="card management-entry" @click="resetAssignmentFilter">
        <h2 class="entry-heading">作业管理</h2>
        <div class="management-entry-content">
          <div class="management-feature">
            <span class="management-feature-icon"><AppIcon name="clipboard" :size="20" /></span>
            <span class="management-feature-copy">
              <strong>作业列表</strong>
              <small>已发布作业、题目与状态</small>
            </span>
          </div>
          <div class="management-feature">
            <span class="management-feature-icon"><AppIcon name="chart" :size="20" /></span>
            <span class="management-feature-copy">
              <strong>学生提交</strong>
              <small>完成进度与作答情况</small>
            </span>
          </div>
        </div>
        <span class="management-entry-action">
          查看全部作业 <AppIcon name="arrow-right" :size="16" />
        </span>
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import AppIcon from '../../components/icons/AppIcon.vue'
import PublishModeCards from '../../components/PublishModeCards.vue'
import { useTeacherStore } from '../../stores/teacher'

const router = useRouter()
const teacher = useTeacherStore()

function openPublish(mode: 'online' | 'offline') {
  void router.push({ path: '/teacher/assignments/new', query: { mode } })
}

function resetAssignmentFilter() {
  teacher.setAssignmentDateFilter('')
}
</script>

<style scoped>
.assignment-hub { max-width: var(--content-frame-width); }
.assignment-entry-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: stretch; gap: 16px; }
.publish-entry, .management-entry { min-width: 0; margin-bottom: 0; padding: 20px; }
.entry-heading { margin-bottom: 16px; color: var(--text); font-size: 18px; font-weight: 700; }
.management-entry {
  display: flex; flex-direction: column; gap: 0; color: var(--text);
  transition: border-color .16s ease, box-shadow .16s ease;
}
.management-entry:hover { border-color: var(--primary); box-shadow: var(--shadow-md); }
.management-entry:focus-visible { outline: 3px solid var(--primary); outline-offset: 2px; }
.publish-entry :deep(.mode-grid) { grid-template-columns: minmax(0, 1fr); }
.publish-entry :deep(.mode-card) { min-height: 145px; padding: 19px 21px; border-radius: var(--radius-control); }
.management-entry-content { display: flex; flex: 1; flex-direction: column; gap: 12px; }
.management-feature { display: flex; min-height: 102px; flex: 1; align-items: center; gap: 13px; padding: 18px; border: 1px solid var(--border); border-radius: var(--radius-control); background: var(--surface-2); }
.management-feature-icon { display: grid; width: 42px; height: 42px; flex: 0 0 auto; place-items: center; border-radius: var(--radius-control); background: var(--primary-50); color: var(--primary); }
.management-feature-copy { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
.management-feature-copy strong { color: var(--text); font-size: 14px; font-weight: 700; }
.management-feature-copy small { color: var(--text-2); font-size: 12px; line-height: 1.5; }
.management-entry-action { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 16px; padding-top: 13px; border-top: 1px solid var(--border); color: var(--primary); font-size: 14px; font-weight: 700; }
@media (max-width: 900px) {
  .assignment-entry-grid { grid-template-columns: minmax(0, 1fr); }
}
@media (prefers-reduced-motion: reduce) { .management-entry { transition: none; } }
</style>
