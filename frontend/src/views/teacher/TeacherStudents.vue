<!-- 教师端：学生列表 —— 进入学生画像的导航页（契约 4.5；v0.4.0 改学生卡片网格） -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>学生</h2>
      <p class="page-sub">按班级维护学生名册；学号用于区分同名学生。点击学生卡片查看学科学习轨迹。</p>
    </div>

    <section class="card roster-card">
      <div class="roster-head">
        <div><h3>班级名册</h3><p class="hint">当前任教学科：{{ subjectLabel }}</p></div>
        <div class="roster-create">
          <input v-model="className" maxlength="64" placeholder="例如：七年级一班" @keydown.enter.prevent="createClass" />
          <button class="btn small" :disabled="savingClass || !className.trim()" @click="createClass">{{ savingClass ? '保存中…' : '建立 / 关联班级' }}</button>
        </div>
      </div>
      <div v-if="classrooms.length" class="class-chips">
        <button
          v-for="room in classrooms" :key="room.id"
          type="button" class="class-chip" :class="{ active: selectedClass?.id === room.id }"
          @click="selectClass(room)"
        >{{ room.name }} <span>{{ room.student_count }} 人</span></button>
      </div>
      <div v-else class="empty small-empty">还没有班级。输入班级名称建立，其他学科老师可以关联同一个班级。</div>
      <div v-if="selectedClass" class="roster-body">
        <div class="roster-form">
          <input v-model="studentName" maxlength="64" placeholder="学生姓名" />
          <input v-model="studentNo" maxlength="32" placeholder="唯一学号" @keydown.enter.prevent="addStudent" />
          <button class="btn secondary small" :disabled="savingStudent || !studentName.trim() || !studentNo.trim()" @click="addStudent">{{ savingStudent ? '保存中…' : '加入班级' }}</button>
        </div>
        <div v-if="rosterError" class="error-msg">{{ rosterError }}</div>
        <div class="roster-list">
          <span v-for="member in classStudents" :key="member.id">{{ member.name }} <b>{{ member.student_no }}</b></span>
          <span v-if="!classStudents.length" class="hint">班级里还没有学生。</span>
        </div>
      </div>
    </section>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-if="!loading">
      <div v-if="students.length" class="stu-grid">
        <router-link
          v-for="s in students"
          :key="s.id"
          :to="`/teacher/students/${s.id}`"
          class="card hoverable stu-card"
        >
          <div class="stu-head">
            <span class="stu-avatar">{{ s.name.slice(0, 1) }}</span>
            <div class="stu-id">
              <div class="stu-name">{{ s.name }}</div>
              <div class="stu-no tnum">{{ s.student_no || '—' }}</div>
            </div>
            <AppIcon name="chevron-right" :size="17" class="stu-arrow" />
          </div>
          <div class="stu-stats">
            <div class="stu-stat"><span class="stu-stat-num tnum">{{ s.submission_count }}</span><span class="stu-stat-label">累计提交</span></div>
            <div class="stu-stat"><span class="stu-stat-num tnum err">{{ s.error_count }}</span><span class="stu-stat-label">累计错误</span></div>
            <div class="stu-stat"><span class="stu-stat-num tnum">{{ errorRate(s) }}</span><span class="stu-stat-label">错误率</span></div>
          </div>
          <div class="stu-bar"><span :style="{ width: errorRateWidth(s) }"></span></div>
        </router-link>
      </div>
      <div v-else class="card"><div class="empty">暂无学生数据。</div></div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useTeacherStore } from '../../stores/teacher'
import type { Classroom, ClassroomStudent, StudentSummary, SubjectAgentCode } from '../../api/types'
import { useAuthStore } from '../../stores/auth'
import AppIcon from '../../components/icons/AppIcon.vue'

const teacher = useTeacherStore()
const auth = useAuthStore()
const students = ref<StudentSummary[]>([])
const classrooms = ref<Classroom[]>([])
const classStudents = ref<ClassroomStudent[]>([])
const selectedClass = ref<Classroom | null>(null)
const className = ref('')
const studentName = ref('')
const studentNo = ref('')
const rosterError = ref('')
const savingClass = ref(false)
const savingStudent = ref(false)
const loading = ref(false)
const error = ref('')
const subjectLabel = computed(() => ({
  chinese: '语文', math: '数学', english: '英语', politics: '道法', history: '历史',
  physics: '物理', chemistry: '化学', geography: '地理', biology: '生物'
} as Record<string, string>)[auth.activeSubject] ?? '未选择')

async function loadClassrooms() {
  classrooms.value = await teacher.fetchClassrooms()
  if (selectedClass.value) {
    selectedClass.value = classrooms.value.find((room) => room.id === selectedClass.value?.id) ?? null
  }
  if (!selectedClass.value && classrooms.value.length) await selectClass(classrooms.value[0])
}

async function selectClass(room: Classroom) {
  selectedClass.value = room
  rosterError.value = ''
  try { classStudents.value = await teacher.fetchClassroomStudents(room.id) }
  catch (e) { rosterError.value = '班级名册加载失败。'; console.error(e) }
}

async function createClass() {
  if (!className.value.trim() || !auth.activeSubject) return
  savingClass.value = true
  rosterError.value = ''
  try {
    const room = await teacher.createClassroom(className.value.trim(), auth.activeSubject as SubjectAgentCode)
    className.value = ''
    await loadClassrooms()
    await selectClass(room)
  } catch (e) { rosterError.value = '班级建立失败：请检查名称和当前任教学科。'; console.error(e) }
  finally { savingClass.value = false }
}

async function addStudent() {
  if (!selectedClass.value || !studentName.value.trim() || !studentNo.value.trim()) return
  savingStudent.value = true
  rosterError.value = ''
  try {
    await teacher.addClassroomStudent(selectedClass.value.id, {
      name: studentName.value.trim(), student_no: studentNo.value.trim()
    })
    studentName.value = ''
    studentNo.value = ''
    await selectClass(selectedClass.value)
    students.value = await teacher.fetchStudents()
  } catch (e) { rosterError.value = '学生录入失败：学号可能已被其他学生使用。'; console.error(e) }
  finally { savingStudent.value = false }
}

// 错误率 = 累计错误 / 累计提交（契约 4.5 口径可直接推导）
function errorRate(s: StudentSummary): string {
  if (!s.submission_count) return '—'
  return `${Math.round((s.error_count / s.submission_count) * 100)}%`
}
function errorRateWidth(s: StudentSummary): string {
  if (!s.submission_count) return '0%'
  return `${Math.min(100, Math.round((s.error_count / s.submission_count) * 100))}%`
}

onMounted(async () => {
  loading.value = true
  try {
    const [items] = await Promise.all([teacher.fetchStudents(), loadClassrooms()])
    students.value = items
  } catch (e) {
    error.value = '学生列表加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.roster-card { margin-bottom: 22px; }
.roster-head { display: flex; justify-content: space-between; gap: 16px; align-items: center; flex-wrap: wrap; }
.roster-head h3 { margin: 0 0 3px; }
.roster-head .hint { margin: 0; }
.roster-create, .roster-form { display: flex; gap: 8px; flex-wrap: wrap; }
.roster-create input { min-width: 210px; }
.class-chips { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; }
.class-chip { padding: 8px 12px; background: var(--bg); border: 1px solid var(--border); color: var(--text-2); border-radius: 10px; cursor: pointer; }
.class-chip span { margin-left: 6px; color: var(--text-3); font-size: 12px; }
.class-chip.active { color: var(--primary); background: var(--primary-50); border-color: var(--primary); }
.roster-body { margin-top: 15px; border-top: 1px solid var(--border); padding-top: 14px; }
.roster-form input:first-child { width: 180px; }
.roster-form input:nth-child(2) { width: 220px; }
.roster-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.roster-list > span { background: var(--bg); border-radius: 8px; padding: 6px 10px; font-size: 13px; }
.roster-list b { margin-left: 6px; color: var(--text-3); font-weight: 500; }
.small-empty { margin: 14px 0 0; }
.stu-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.stu-card { margin-bottom: 0; color: var(--text); display: block; }
.stu-head { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.stu-avatar {
  width: 44px; height: 44px; border-radius: 50%; flex-shrink: 0;
  background: var(--primary-50); color: var(--primary);
  font-size: 18px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
}
.stu-id { flex: 1; min-width: 0; }
.stu-name { font-size: 16.5px; font-weight: 700; }
.stu-no { font-size: 12.5px; color: var(--text-3); }
.stu-arrow { color: var(--text-3); }
.stu-stats { display: flex; gap: 10px; }
.stu-stat {
  flex: 1; background: var(--bg); border-radius: 10px; padding: 9px 6px;
  display: flex; flex-direction: column; align-items: center; gap: 1px;
}
.stu-stat-num { font-size: 19px; font-weight: 800; color: var(--primary); line-height: 1.25; }
.stu-stat-num.err { color: var(--red); }
.stu-stat-label { font-size: 12px; color: var(--text-2); }
.stu-bar { height: 6px; background: #EDF0F4; border-radius: 3px; overflow: hidden; margin-top: 12px; }
.stu-bar > span { display: block; height: 100%; background: var(--amber); border-radius: 3px; }
</style>
