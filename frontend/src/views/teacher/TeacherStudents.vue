<!-- 教师端：先选择班级，再进入班级花名册维护学生。 -->
<template>
  <div class="page students-page">
    <header class="page-head">
      <template v-if="!isRosterPage">
        <div class="students-page-heading">
          <h1>学生</h1>
          <button type="button" class="btn" @click="classFormOpen = !classFormOpen">
            <AppIcon :name="classFormOpen ? 'x' : 'plus'" :size="17" />
            {{ classFormOpen ? '收起' : '新建 / 关联班级' }}
          </button>
        </div>
      </template>
      <template v-else>
        <div class="students-page-heading">
          <h1>{{ selectedClass?.name ?? '班级' }}</h1>
          <button type="button" class="btn" :disabled="!selectedClass" @click="studentFormOpen = !studentFormOpen">
            <AppIcon :name="studentFormOpen ? 'x' : 'plus'" :size="17" />
            {{ studentFormOpen ? '收起' : '添加学生' }}
          </button>
        </div>
      </template>
    </header>

    <div v-if="pageError" class="error-msg" role="alert">{{ pageError }}</div>
    <div v-if="loading" class="loading" role="status">加载中…</div>

    <template v-if="!loading && !isRosterPage">
      <form v-if="classFormOpen" class="card entry-form" @submit.prevent="createClass">
        <div class="entry-form-fields">
          <div class="form-row">
            <label for="new-class-name">班级名称</label>
            <input id="new-class-name" v-model="className" type="text" maxlength="64" placeholder="例如：七年级一班" required />
          </div>
          <div class="entry-form-actions">
            <button type="button" class="btn secondary" :disabled="savingClass" @click="classFormOpen = false">取消</button>
            <button type="submit" class="btn" :disabled="savingClass || !className.trim()">
              {{ savingClass ? '保存中…' : '建立 / 关联班级' }}
            </button>
          </div>
        </div>
        <p class="form-note">同名班级会关联到当前任教学科。</p>
      </form>

      <section v-if="classrooms.length" class="class-list" aria-label="班级列表">
        <router-link
          v-for="room in classrooms"
          :key="room.id"
          :to="`/teacher/students/classes/${room.id}`"
          class="class-row"
        >
          <span class="class-icon"><AppIcon name="users" :size="19" /></span>
          <span class="class-main">
            <strong>{{ room.name }}</strong>
            <span class="class-subjects">
              <span v-for="subject in room.subjects" :key="subject">{{ subjectName(subject) }}</span>
              <span v-if="!room.subjects?.length">{{ subjectLabel }}</span>
            </span>
          </span>
          <span class="class-count tnum">{{ room.student_count }}<small>人</small></span>
          <AppIcon name="chevron-right" :size="18" class="class-arrow" />
        </router-link>
      </section>
      <section v-else-if="!pageError" class="card empty-classes">
        <span class="empty-icon"><AppIcon name="users" :size="22" /></span>
        <p>还没有班级</p>
      </section>
    </template>

    <template v-if="!loading && isRosterPage && selectedClass">
      <div class="roster-toolbar">
        <router-link to="/teacher/students" class="back-link">
          <AppIcon name="chevron-left" :size="16" /> 班级列表
        </router-link>
        <div class="roster-total">
          <AppIcon name="users" :size="16" />
          <span>{{ selectedClass.student_count ?? 0 }} 名学生</span>
        </div>
      </div>

      <form v-if="studentFormOpen" class="card entry-form student-entry-form" @submit.prevent="addStudent">
        <div class="entry-form-fields student-form-fields">
          <div class="form-row">
            <label for="new-student-name">学生姓名</label>
            <input id="new-student-name" v-model="studentName" type="text" maxlength="64" autocomplete="off" required />
          </div>
          <div class="form-row">
            <label for="new-student-number">学号</label>
            <input id="new-student-number" v-model="studentNo" type="text" maxlength="32" autocomplete="off" required @keydown.enter.prevent="addStudent" />
          </div>
          <div class="entry-form-actions">
            <button type="button" class="btn secondary" :disabled="savingStudent" @click="studentFormOpen = false">取消</button>
            <button type="submit" class="btn" :disabled="savingStudent || !studentName.trim() || !studentNo.trim()">
              {{ savingStudent ? '保存中…' : '加入班级' }}
            </button>
          </div>
        </div>
      </form>

      <section class="roster-section" aria-label="班级学生列表">
        <div v-if="rosterError" class="error-msg" role="alert">{{ rosterError }}</div>
        <div v-else-if="rosterCards.length" class="student-list-wrap">
          <table class="student-list">
            <thead>
              <tr>
                <th scope="col">学生</th>
                <th scope="col">累计提交</th>
                <th scope="col">累计错误</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="student in rosterCards" :key="student.id">
                <td>
                  <router-link :to="`/teacher/students/${student.id}`" class="student-identity">
                    <span class="student-avatar">{{ student.name.slice(0, 1) }}</span>
                    <span class="student-name-block">
                      <strong>{{ student.name }}</strong>
                      <small class="tnum">{{ student.student_no || '暂无学号' }}</small>
                    </span>
                  </router-link>
                </td>
                <td class="student-metric tnum">{{ student.summary?.submission_count ?? 0 }}</td>
                <td class="student-metric metric-errors tnum">{{ student.summary?.error_count ?? 0 }}</td>
                <td>
                  <div class="student-actions">
                    <button type="button" class="btn ghost small" :aria-label="`编辑${student.name}的信息`" @click="openEdit(student)">
                      <AppIcon name="edit" :size="15" /> 编辑
                    </button>
                    <button type="button" class="btn small delete-button" :aria-label="`从当前班级删除${student.name}`" @click="pendingDelete = student">
                      <AppIcon name="trash" :size="15" /> 删除
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="card empty-roster">
          <span>这个班级还没有学生</span>
          <button type="button" class="btn secondary small" @click="studentFormOpen = true">添加学生</button>
        </div>
      </section>
    </template>

    <div v-if="editingStudent" class="student-modal-mask" tabindex="-1" @click.self="closeEdit" @keydown.esc.stop="closeEdit">
      <section class="student-modal" role="dialog" aria-modal="true" aria-labelledby="edit-student-title">
        <h3 id="edit-student-title">编辑学生信息</h3>
        <p class="student-modal-note">修改后会同步到该学生关联的班级，学生需使用新姓名和学号登录。</p>
        <form class="student-edit-form" @submit.prevent="saveStudentInfo">
          <div class="form-row">
            <label for="edit-student-name">学生姓名</label>
            <input id="edit-student-name" v-model="editName" type="text" maxlength="64" required />
          </div>
          <div class="form-row">
            <label for="edit-student-number">学号</label>
            <input id="edit-student-number" v-model="editStudentNo" type="text" maxlength="32" required />
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

    <div v-if="pendingDelete" class="student-modal-mask" tabindex="-1" @click.self="closeDelete" @keydown.esc.stop="closeDelete">
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
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTeacherStore } from '../../stores/teacher'
import type { Classroom, ClassroomStudent, StudentSummary, SubjectAgentCode } from '../../api/types'
import { useAuthStore } from '../../stores/auth'
import { getSubjectLabel } from '../../utils/subjectLabels'
import AppIcon from '../../components/icons/AppIcon.vue'

const teacher = useTeacherStore()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const students = ref<StudentSummary[]>([])
const classrooms = ref<Classroom[]>([])
const classStudents = ref<ClassroomStudent[]>([])
const selectedClass = ref<Classroom | null>(null)
const classFormOpen = ref(false)
const studentFormOpen = ref(false)
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
const pageError = ref('')
let loadSequence = 0

const classRouteParam = computed(() => route.params.classroomId)
const currentClassroomId = computed(() => {
  const raw = classRouteParam.value
  const id = Number(Array.isArray(raw) ? raw[0] : raw)
  return Number.isInteger(id) && id > 0 ? id : null
})
const isRosterPage = computed(() => classRouteParam.value !== undefined)
const subjectLabel = computed(() => auth.activeSubject ? getSubjectLabel(auth.activeSubject, auth.activeSubject) : '未选择任教学科')
const rosterCards = computed(() => classStudents.value.map((member) => ({
  ...member,
  summary: students.value.find((student) => student.id === member.id),
})))

function subjectName(subject: string): string {
  return getSubjectLabel(subject, subject)
}

async function loadPage() {
  const sequence = ++loadSequence
  const classroomId = currentClassroomId.value
  loading.value = true
  pageError.value = ''
  rosterError.value = ''
  selectedClass.value = null
  classStudents.value = []
  students.value = []

  try {
    const rooms = await teacher.fetchClassrooms()
    if (sequence !== loadSequence) return
    classrooms.value = rooms
    if (!isRosterPage.value) return
    if (classroomId === null) {
      pageError.value = '班级地址无效。'
      return
    }
    const room = rooms.find((item) => item.id === classroomId)
    if (!room) {
      pageError.value = '未找到这个班级。'
      return
    }
    selectedClass.value = room
    const [studentItems, members] = await Promise.all([
      teacher.fetchStudents(),
      teacher.fetchClassroomStudents(room.id),
    ])
    if (sequence !== loadSequence) return
    students.value = studentItems
    classStudents.value = members
  } catch (e) {
    if (sequence === loadSequence) pageError.value = '页面加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

watch(classRouteParam, () => { void loadPage() }, { immediate: true })

async function createClass() {
  const name = className.value.trim()
  if (!name || !auth.activeSubject) return
  savingClass.value = true
  pageError.value = ''
  try {
    const room = await teacher.createClassroom(name, auth.activeSubject as SubjectAgentCode)
    className.value = ''
    classFormOpen.value = false
    await router.push(`/teacher/students/classes/${room.id}`)
  } catch (e) {
    pageError.value = '班级建立失败：请检查名称和当前任教学科。'
    console.error(e)
  } finally {
    savingClass.value = false
  }
}

async function addStudent() {
  const room = selectedClass.value
  if (!room || !studentName.value.trim() || !studentNo.value.trim()) return
  savingStudent.value = true
  rosterError.value = ''
  try {
    await teacher.addClassroomStudent(room.id, {
      name: studentName.value.trim(), student_no: studentNo.value.trim()
    })
    studentName.value = ''
    studentNo.value = ''
    studentFormOpen.value = false
    await loadPage()
  } catch (e) {
    rosterError.value = '学生录入失败：学号可能已被其他学生使用。'
    console.error(e)
  } finally {
    savingStudent.value = false
  }
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
  const room = selectedClass.value
  const student = editingStudent.value
  if (!room || !student) return
  savingStudentInfo.value = true
  editError.value = ''
  try {
    const updated = await teacher.updateClassroomStudent(room.id, student.id, {
      name: editName.value.trim(), student_no: editStudentNo.value.trim()
    })
    classStudents.value = classStudents.value.map((item) => item.id === updated.id ? updated : item)
    students.value = students.value.map((item) => item.id === updated.id
      ? { ...item, name: updated.name, student_no: updated.student_no }
      : item)
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
  const room = selectedClass.value
  const student = pendingDelete.value
  if (!room || !student) return
  deletingStudentId.value = student.id
  deleteError.value = ''
  try {
    await teacher.removeClassroomStudent(room.id, student.id)
    classStudents.value = classStudents.value.filter((item) => item.id !== student.id)
    classrooms.value = classrooms.value.map((item) => item.id === room.id
      ? { ...item, student_count: Math.max(0, item.student_count - 1) }
      : item)
    selectedClass.value = classrooms.value.find((item) => item.id === room.id) ?? room
    pendingDelete.value = null
  } catch (e) {
    deleteError.value = '删除失败，请稍后重试。'
    console.error(e)
  } finally {
    deletingStudentId.value = null
  }
}

</script>

<style scoped>
.students-page { max-width: var(--content-frame-width); padding-top: 0; }
.students-page .page-head { min-height: 86px; display: flex; flex-direction: column; justify-content: center; gap: 8px; }
.students-page-heading { display: flex; width: 100%; min-height: 50px; align-items: center; justify-content: space-between; gap: 20px; }
.students-page-heading h1 { min-width: 0; overflow: hidden; color: var(--text); font-size: clamp(21px, 2vw, 25px); font-weight: 720; letter-spacing: -0.035em; line-height: 1.2; text-overflow: ellipsis; white-space: nowrap; }
.students-page-heading > .btn { flex: 0 0 auto; }
.roster-toolbar { display: flex; min-height: 38px; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.roster-total { display: inline-flex; align-items: center; gap: 7px; color: var(--text-2); font-size: 13px; white-space: nowrap; }
.roster-total :deep(.app-icon) { color: var(--primary); }
.entry-form { margin-bottom: 18px; }
.entry-form-fields { display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
.entry-form .form-row { width: min(360px, 100%); margin: 0; }
.entry-form-actions { display: flex; gap: 8px; }
.form-note { margin-top: 10px; color: var(--text-3); font-size: 12px; }
.class-list { display: flex; flex-direction: column; gap: 10px; }
.class-row { display: flex; min-height: 78px; align-items: center; gap: 16px; padding: 15px 18px; border: 1px solid var(--border); border-radius: var(--radius-surface); background: var(--card); box-shadow: var(--shadow); transition: border-color .16s ease, transform .16s ease, box-shadow .16s ease; }
.class-row:hover { transform: translateY(-1px); border-color: var(--border-strong); box-shadow: var(--shadow-md); }
.class-icon, .empty-icon { display: grid; width: 44px; height: 44px; flex: 0 0 auto; place-items: center; border-radius: var(--radius-control); background: var(--primary-50); color: var(--primary); }
.class-main { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 3px; }
.class-main strong { overflow: hidden; color: var(--text); font-size: 15px; text-overflow: ellipsis; white-space: nowrap; }
.class-subjects { display: flex; flex-wrap: wrap; gap: 5px; color: var(--text-3); font-size: 12px; }
.class-subjects > span { padding: 1px 7px; border-radius: var(--radius-pill); background: var(--surface-2); }
.class-count { min-width: 52px; color: var(--text-strong); font-size: 17px; font-weight: 750; text-align: right; }
.class-count small { margin-left: 3px; color: var(--text-3); font-size: 12px; font-weight: 500; }
.class-arrow { color: var(--text-3); }
.empty-classes { display: flex; min-height: 230px; flex-direction: column; align-items: center; justify-content: center; gap: 13px; margin-bottom: 0; color: var(--text-2); }
.empty-classes p { font-size: 14px; }
.roster-section { width: 100%; }
.student-entry-form { margin-bottom: 17px; }
.student-form-fields .form-row { width: min(250px, 100%); }
.student-list-wrap { max-width: 100%; overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius-surface); background: var(--card); box-shadow: var(--shadow); }
.student-list { width: 100%; min-width: 700px; border-collapse: collapse; table-layout: fixed; }
.student-list th, .student-list td { padding: 13px 18px; border-bottom: 1px solid var(--border); vertical-align: middle; }
.student-list th { background: var(--surface-2); color: var(--text-2); font-size: 12px; font-weight: 650; text-align: left; }
.student-list th:first-child { width: 42%; }
.student-list th:nth-child(2), .student-list th:nth-child(3) { width: 14%; text-align: center; }
.student-list th:last-child { width: 30%; text-align: right; }
.student-list td:nth-child(2), .student-list td:nth-child(3) { text-align: center; }
.student-list td:last-child { text-align: right; }
.student-list tbody tr:last-child td { border-bottom: 0; }
.student-list tbody tr:hover { background: var(--surface-2); }
.student-identity { display: flex; min-width: 0; align-items: center; gap: 12px; color: var(--text); }
.student-identity:hover .student-name-block strong { color: var(--primary); }
.student-avatar { display: grid; width: 42px; height: 42px; flex: 0 0 auto; place-items: center; border-radius: 50%; background: var(--primary-50); color: var(--primary); font-size: 17px; font-weight: 700; }
.student-name-block { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
.student-name-block strong { overflow: hidden; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.student-name-block small { color: var(--text-3); font-size: 12px; }
.student-metric { color: var(--primary); font-size: 15px; font-weight: 700; }
.student-metric.metric-errors { color: var(--red); }
.student-actions { display: flex; align-items: center; justify-content: flex-end; gap: 5px; }
.student-actions .btn { display: inline-flex; align-items: center; gap: 5px; }
.delete-button { border: 1px solid var(--border); background: #fff; color: var(--red); font-weight: 550; }
.delete-button:hover { background: var(--red-bg); }
.empty-roster { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 0; color: var(--text-2); }
.student-modal-mask { position: fixed; inset: 0; z-index: 300; display: flex; align-items: center; justify-content: center; padding: 20px; background: rgba(15, 23, 42, .4); }
.student-modal { width: min(440px, 100%); padding: 22px 24px; border: 1px solid var(--border); border-radius: var(--radius-panel); background: var(--card); box-shadow: var(--shadow-lg); }
.student-modal h3 { font-size: 16.5px; }
.student-modal-note { margin-top: 10px; color: var(--text-2); font-size: 13px; }
.student-edit-form { margin-top: 16px; }
.student-edit-form .form-row { margin-bottom: 12px; }
.student-modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
@media (max-width: 760px) {
  .students-page .page-head { min-height: 64px; }
  .students-page-heading { min-height: 44px; gap: 12px; }
  .students-page-heading h1 { font-size: 20px; }
}
@media (max-width: 480px) {
  .students-page-heading { gap: 8px; }
  .students-page-heading > .btn { padding-inline: 10px; font-size: 12px; }
  .roster-toolbar { min-height: 34px; }
  .entry-form-fields, .student-form-fields { align-items: stretch; flex-direction: column; }
  .entry-form .form-row, .student-form-fields .form-row { width: 100%; }
  .entry-form-actions { justify-content: flex-end; }
  .class-row { gap: 11px; padding: 13px; }
  .class-icon { width: 39px; height: 39px; }
  .student-modal { padding: 20px; }
  .student-modal-actions .btn { padding-inline: 14px; }
}
@media (prefers-reduced-motion: reduce) { .class-row { transition: none; } }
</style>
