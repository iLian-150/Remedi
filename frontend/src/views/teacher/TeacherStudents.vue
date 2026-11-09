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
          <input v-model="className" type="text" maxlength="64" placeholder="例如：七年级一班" @keydown.enter.prevent="createClass" />
          <button type="button" class="btn" :disabled="savingClass || !className.trim()" @click="createClass">{{ savingClass ? '保存中…' : '建立 / 关联班级' }}</button>
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
          <input v-model="studentName" type="text" maxlength="64" placeholder="学生姓名" />
          <input v-model="studentNo" type="text" maxlength="32" placeholder="唯一学号" @keydown.enter.prevent="addStudent" />
          <button type="button" class="btn secondary" :disabled="savingStudent || !studentName.trim() || !studentNo.trim()" @click="addStudent">{{ savingStudent ? '保存中…' : '加入班级' }}</button>
        </div>
        <div v-if="rosterError" class="error-msg">{{ rosterError }}</div>
      </div>
    </section>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-if="!loading">
      <div v-if="rosterCards.length" class="stu-grid">
        <article
          v-for="s in rosterCards"
          :key="s.id"
          class="card hoverable stu-card"
        >
          <router-link :to="`/teacher/students/${s.id}`" class="stu-card-link">
            <div class="stu-head">
              <span class="stu-avatar">{{ s.name.slice(0, 1) }}</span>
              <div class="stu-id">
                <div class="stu-name">{{ s.name }}</div>
                <div class="stu-no tnum">{{ s.student_no || '—' }}</div>
              </div>
              <AppIcon name="chevron-right" :size="17" class="stu-arrow" />
            </div>
            <div class="stu-stats">
              <div class="stu-stat"><span class="stu-stat-num tnum">{{ s.summary?.submission_count ?? 0 }}</span><span class="stu-stat-label">累计提交</span></div>
              <div class="stu-stat"><span class="stu-stat-num tnum err">{{ s.summary?.error_count ?? 0 }}</span><span class="stu-stat-label">累计错误</span></div>
              <div class="stu-stat"><span class="stu-stat-num tnum">{{ errorRate(s.summary) }}</span><span class="stu-stat-label">错误率</span></div>
            </div>
            <div class="stu-bar"><span :style="{ width: errorRateWidth(s.summary) }"></span></div>
          </router-link>
          <div class="stu-actions">
            <button type="button" class="btn ghost small" :aria-label="`编辑${s.name}的信息`" @click="openEdit(s)">
              <AppIcon name="edit" :size="15" /> 编辑
            </button>
            <button type="button" class="btn small stu-delete-btn" :aria-label="`从当前班级删除${s.name}`" @click="pendingDelete = s">
              <AppIcon name="trash" :size="15" /> 删除
            </button>
          </div>
        </article>
      </div>
    </template>

    <div v-if="editingStudent" class="student-modal-mask" @click.self="closeEdit" @keydown.esc.stop="closeEdit">
      <section class="student-modal" role="dialog" aria-modal="true" aria-labelledby="edit-student-title">
        <h3 id="edit-student-title">编辑学生信息</h3>
        <p class="student-modal-note">修改后会同步到该学生关联的班级，学生需使用新姓名和学号登录。</p>
        <form class="student-edit-form" @submit.prevent="saveStudentInfo">
          <div class="form-row">
            <label for="edit-student-name">学生姓名</label>
            <input id="edit-student-name" v-model="editName" type="text" maxlength="64" required />
          </div>
          <div class="form-row">
            <label for="edit-student-no">学号</label>
            <input id="edit-student-no" v-model="editStudentNo" type="text" maxlength="32" required />
          </div>
          <div v-if="editError" class="error-msg" role="alert">{{ editError }}</div>
          <div class="student-modal-actions">
            <button type="button" class="btn secondary" :disabled="savingStudentInfo" @click="closeEdit">取消</button>
            <button type="submit" class="btn" :disabled="savingStudentInfo || !editName.trim() || !editStudentNo.trim()">
              {{ savingStudentInfo ? '保存中…' : '保存修改' }}
            </button>
          </div>
        </form>
      </section>
    </div>

    <div v-if="pendingDelete" class="student-modal-mask" @click.self="closeDelete" @keydown.esc.stop="closeDelete">
      <section class="student-modal" role="dialog" aria-modal="true" aria-labelledby="delete-student-title">
        <h3 id="delete-student-title">从班级删除学生</h3>
        <p class="student-modal-note">确定将 {{ pendingDelete.name }} 从当前班级名册中移除吗？没有其他班级名册时，该学生将无法登录；历史学习记录会保留。</p>
        <div v-if="deleteError" class="error-msg" role="alert">{{ deleteError }}</div>
        <div class="student-modal-actions">
          <button type="button" class="btn secondary" :disabled="deletingStudentId !== null" @click="closeDelete">取消</button>
          <button type="button" class="btn danger" :disabled="deletingStudentId !== null" @click="confirmDeleteStudent">
            {{ deletingStudentId === pendingDelete.id ? '删除中…' : '确认删除' }}
          </button>
        </div>
      </section>
    </div>
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
const rosterCards = computed(() => classStudents.value.map((member) => ({
  ...member,
  summary: students.value.find((student) => student.id === member.id),
})))
const className = ref('')
const studentName = ref('')
const studentNo = ref('')
const rosterError = ref('')
const editingStudent = ref<ClassroomStudent | null>(null)
const editName = ref('')
const editStudentNo = ref('')
const editError = ref('')
const savingStudentInfo = ref(false)
const pendingDelete = ref<ClassroomStudent | null>(null)
const deleteError = ref('')
const deletingStudentId = ref<number | null>(null)
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
  classStudents.value = []
  rosterError.value = ''
  try {
    const members = await teacher.fetchClassroomStudents(room.id)
    if (selectedClass.value?.id === room.id) classStudents.value = members
  } catch (e) {
    if (selectedClass.value?.id === room.id) rosterError.value = '班级名册加载失败。'
    console.error(e)
  }
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

function openEdit(student: ClassroomStudent) {
  editingStudent.value = student
  editName.value = student.name
  editStudentNo.value = student.student_no
  editError.value = ''
}

function closeEdit() {
  if (savingStudentInfo.value) return
  editingStudent.value = null
  editError.value = ''
}

async function saveStudentInfo() {
  if (!selectedClass.value || !editingStudent.value) return
  savingStudentInfo.value = true
  editError.value = ''
  try {
    const updated = await teacher.updateClassroomStudent(selectedClass.value.id, editingStudent.value.id, {
      name: editName.value.trim(), student_no: editStudentNo.value.trim()
    })
    classStudents.value = classStudents.value.map((student) => student.id === updated.id ? updated : student)
    students.value = students.value.map((student) => student.id === updated.id
      ? { ...student, name: updated.name, student_no: updated.student_no }
      : student)
    editingStudent.value = null
  } catch (e) {
    editError.value = '保存失败，请检查姓名和学号是否有效，学号也可能已被使用。'
    console.error(e)
  } finally {
    savingStudentInfo.value = false
  }
}

function closeDelete() {
  if (deletingStudentId.value !== null) return
  pendingDelete.value = null
  deleteError.value = ''
}

async function confirmDeleteStudent() {
  if (!selectedClass.value || !pendingDelete.value) return
  const classroomId = selectedClass.value.id
  const studentId = pendingDelete.value.id
  deletingStudentId.value = studentId
  deleteError.value = ''
  try {
    await teacher.removeClassroomStudent(classroomId, studentId)
    classStudents.value = classStudents.value.filter((student) => student.id !== studentId)
    classrooms.value = classrooms.value.map((room) => room.id === classroomId
      ? { ...room, student_count: Math.max(0, room.student_count - 1) }
      : room)
    selectedClass.value = classrooms.value.find((room) => room.id === classroomId) ?? selectedClass.value
    pendingDelete.value = null
  } catch (e) {
    deleteError.value = '删除失败，请稍后重试。'
    console.error(e)
  } finally {
    deletingStudentId.value = null
  }
}

// 错误率 = 累计错误 / 累计提交（契约 4.5 口径可直接推导）
type StudentLearningStats = Pick<StudentSummary, 'submission_count' | 'error_count'>
function errorRate(s?: StudentLearningStats): string {
  if (!s?.submission_count) return '—'
  return `${Math.round((s.error_count / s.submission_count) * 100)}%`
}
function errorRateWidth(s?: StudentLearningStats): string {
  if (!s?.submission_count) return '0%'
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
.roster-create, .roster-form { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.roster-create input { width: min(252px, 100%); min-width: min(210px, 100%); }
.class-chips { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; }
.class-chip { padding: 8px 12px; background: var(--bg); border: 1px solid var(--border); color: var(--text-2); border-radius: 10px; cursor: pointer; }
.class-chip span { margin-left: 6px; color: var(--text-3); font-size: 12px; }
.class-chip.active { color: var(--primary); background: var(--primary-50); border-color: var(--primary); }
.roster-body { margin-top: 15px; border-top: 1px solid var(--border); padding-top: 14px; }
.roster-form input:first-child { width: 180px; }
.roster-form input:nth-child(2) { width: 220px; }
.small-empty { margin: 14px 0 0; }
.stu-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.stu-card { margin-bottom: 0; color: var(--text); }
.stu-card-link { color: var(--text); display: block; }
.stu-actions { display: flex; justify-content: flex-end; gap: 6px; margin-top: 12px; padding-top: 9px; border-top: 1px solid var(--border); }
.stu-actions .btn { display: inline-flex; align-items: center; gap: 5px; }
.stu-delete-btn { background: #fff; color: var(--red); border: 1px solid var(--border); font-weight: 500; }
.stu-delete-btn:hover { background: var(--red-bg); }
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
.student-modal-mask { position: fixed; inset: 0; z-index: 300; display: flex; align-items: center; justify-content: center; padding: 20px; background: rgba(15, 23, 42, .4); }
.student-modal { width: min(440px, 100%); padding: 22px 24px; border: 1px solid var(--border); border-radius: 14px; background: var(--card); box-shadow: var(--shadow-lg); }
.student-modal h3 { font-size: 16.5px; }
.student-modal-note { margin-top: 10px; color: var(--text-2); font-size: 14px; }
.student-edit-form { margin-top: 16px; }
.student-edit-form .form-row { margin-bottom: 12px; }
.student-modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
@media (max-width: 480px) {
  .student-modal { padding: 20px; }
  .student-modal-actions .btn { padding-inline: 14px; }
}
</style>
