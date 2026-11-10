<template>
  <div class="page assignment-hub">
    <div class="assignment-entry-grid">
      <section class="card publish-entry">
        <h2 class="entry-heading">发布作业</h2>
        <PublishModeCards @choose="openPublish" />
      </section>

      <div class="assignment-aside">
        <router-link to="/teacher/assignments/manage" class="card management-entry" @click="resetAssignmentFilter">
          <span class="management-entry-icon"><AppIcon name="clipboard" :size="21" /></span>
          <strong>作业管理</strong>
          <AppIcon name="arrow-right" :size="18" class="management-entry-arrow" />
        </router-link>
        <DailyAssignmentSummary />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import AppIcon from '../../components/icons/AppIcon.vue'
import PublishModeCards from '../../components/PublishModeCards.vue'
import DailyAssignmentSummary from '../../components/DailyAssignmentSummary.vue'
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
.assignment-entry-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; gap: 16px; }
.publish-entry, .management-entry { min-width: 0; margin-bottom: 0; padding: 20px; }
.entry-heading { margin-bottom: 16px; color: var(--text); font-size: 18px; font-weight: 700; }
.assignment-aside { display: grid; min-width: 0; gap: 16px; }
.management-entry {
  display: flex; min-height: 96px; align-items: center; gap: 14px; padding: 20px 22px;
  color: var(--text); font-size: 17px; font-weight: 700; text-decoration: none;
  transition: border-color .16s ease, box-shadow .16s ease;
}
.management-entry:hover { border-color: var(--primary); box-shadow: var(--shadow-md); }
.management-entry:focus-visible { outline: 3px solid var(--primary); outline-offset: 2px; }
.management-entry-icon { display: grid; width: 48px; height: 48px; flex: 0 0 auto; place-items: center; border-radius: var(--radius-control); background: var(--primary-50); color: var(--primary); }
.management-entry-arrow { margin-left: auto; color: var(--text-3); }
.publish-entry :deep(.mode-grid) { grid-template-columns: minmax(0, 1fr); }
.publish-entry :deep(.mode-card) { min-height: 145px; padding: 19px 21px; border-radius: var(--radius-control); }
@media (max-width: 900px) {
  .assignment-entry-grid { grid-template-columns: minmax(0, 1fr); }
}
@media (prefers-reduced-motion: reduce) { .management-entry { transition: none; } }
</style>
