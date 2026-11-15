<template>
  <div class="page">
    <div v-if="error" class="error-msg" role="alert">
      {{ error }} <button type="button" class="btn small secondary" @click="loadProfile">重试</button>
    </div>
    <div v-else-if="loading" class="loading" role="status">加载中…</div>

    <template v-else-if="profile">
      <section class="board-frame" aria-label="学习概览">
        <div class="board">
          <h2 class="chalk-name chalk">{{ profile.student.name }}</h2>
          <p class="chalk-meta chalk-dim">学号 <span class="chalk tnum">{{ profile.student.student_no || '—' }}</span></p>

          <div class="chalk-divider"></div>

          <div class="board-stats">
            <div class="board-stat">
              <div class="board-stat-num chalk tnum">{{ profile.knowledge_analysis.graded_question_count }}</div>
              <div class="board-stat-label chalk-dim">已批改题目</div>
            </div>
            <div class="board-stat">
              <div class="board-stat-num chalk tnum">{{ profile.knowledge_analysis.wrong_question_count }}</div>
              <div class="board-stat-label chalk-dim">出错题目</div>
            </div>
            <div class="board-stat">
              <div class="board-stat-num chalk chalk-yellow tnum">{{ profile.knowledge_analysis.pending_correction_count }}</div>
              <div class="board-stat-label chalk-dim">待订正记录</div>
            </div>
            <div class="board-stat">
              <div class="board-stat-num chalk chalk-green tnum">{{ profile.knowledge_analysis.corrected_count }}</div>
              <div class="board-stat-label chalk-dim">已订正记录</div>
            </div>
          </div>

          <div class="board-ledge" aria-hidden="true">
            <span class="chalk-stick"></span>
            <span class="chalk-stick short"></span>
            <span class="board-eraser"></span>
          </div>
        </div>
      </section>

      <StudentKnowledgeAnalysis :analysis="profile.knowledge_analysis" audience="student" />
      <StudentProfileRecords :profile="profile" audience="student" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useStudentStore } from '../../stores/student'
import type { StudentProfile } from '../../api/types'
import StudentKnowledgeAnalysis from '../../components/StudentKnowledgeAnalysis.vue'
import StudentProfileRecords from '../../components/StudentProfileRecords.vue'

const student = useStudentStore()
const profile = ref<StudentProfile | null>(null)
const loading = ref(true)
const error = ref('')

async function loadProfile() {
  loading.value = true
  error.value = ''
  try {
    profile.value = await student.fetchProfile()
  } catch (e) {
    error.value = '档案加载失败。'
    console.error(e)
  } finally {
    loading.value = false
  }
}

onMounted(loadProfile)
</script>

<style scoped>
/* ================= 学习黑板 ================= */
.board-frame {
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.14), rgba(0, 0, 0, 0.12)),
    repeating-linear-gradient(93deg, #8A5A33 0 46px, #96683D 46px 52px, #7C4F2A 52px 104px);
  border-radius: var(--radius-surface);
  padding: 14px;
  box-shadow: var(--shadow-lg), inset 0 2px 3px rgba(255, 255, 255, 0.25), inset 0 -3px 6px rgba(0, 0, 0, 0.3);
  margin-bottom: 16px;
}
.board {
  position: relative;
  background:
    radial-gradient(120% 90% at 30% 0%, rgba(255, 255, 255, 0.07), transparent 55%),
    repeating-linear-gradient(115deg, rgba(255, 255, 255, 0.016) 0 26px, transparent 26px 52px),
    linear-gradient(160deg, #33584A 0%, #2E4B3F 55%, #29473B 100%);
  border-radius: var(--radius-control);
  padding: 26px 30px 20px;
  box-shadow: inset 0 0 42px rgba(0, 0, 0, 0.35), inset 0 2px 8px rgba(0, 0, 0, 0.3);
  overflow: hidden;
}
.chalk {
  font-family: 'KaiTi', 'STKaiti', 'Kaiti SC', 'Segoe Print', 'Bradley Hand', 'Comic Sans MS', cursive;
  color: #F7F3E8;
  text-shadow: 0 0 1px rgba(247, 243, 232, 0.55), 0 0 7px rgba(247, 243, 232, 0.14);
  letter-spacing: 0.5px;
}
.chalk-dim {
  font-family: 'KaiTi', 'STKaiti', 'Kaiti SC', 'Segoe Print', 'Bradley Hand', 'Comic Sans MS', cursive;
  color: rgba(240, 238, 226, 0.72);
  letter-spacing: 0.5px;
}
.chalk-yellow { color: #FFE58A; text-shadow: 0 0 1px rgba(255, 229, 138, 0.6), 0 0 8px rgba(255, 229, 138, 0.2); }
.chalk-green { color: #B5E7A0; text-shadow: 0 0 1px rgba(181, 231, 160, 0.6), 0 0 8px rgba(181, 231, 160, 0.2); }
.chalk-name { font-size: 38px; font-weight: 700; line-height: 1.15; overflow-wrap: anywhere; }
.chalk-meta { margin-top: 6px; font-size: 15px; overflow-wrap: anywhere; }
.chalk-divider { height: 0; margin: 18px 0 4px; border-top: 2px dashed rgba(247, 243, 232, 0.4); transform: rotate(-0.15deg); }
.board-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }
.board-stat { min-width: 0; text-align: left; }
.board-stat-num { font-size: clamp(26px, 2.5vw, 34px); font-weight: 700; line-height: 1.1; }
.board-stat-label { margin-top: 2px; font-size: 13.5px; }
.board-ledge { display: flex; align-items: flex-end; gap: 8px; margin-top: 18px; }
.chalk-stick {
  width: 44px; height: 7px; border-radius: var(--radius-micro);
  background: linear-gradient(180deg, #FFFFFF, #E9E4D2);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35); transform: rotate(-2deg);
}
.chalk-stick.short { width: 26px; transform: rotate(1.5deg); background: linear-gradient(180deg, #FFE58A, #F3D97B); }
.board-eraser {
  width: 56px; height: 15px; margin-left: auto; border-radius: var(--radius-micro);
  background: linear-gradient(180deg, #B08954 0 55%, #4B4B4B 55% 100%);
  box-shadow: 0 2px 3px rgba(0, 0, 0, 0.4); transform: rotate(-1deg);
}

@media (max-width: 720px) {
  .board-frame { padding: 9px; }
  .board { padding: 20px 18px 16px; }
  .chalk-name { font-size: 31px; }
  .board-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .board-stat-num { font-size: 29px; }
}
</style>
