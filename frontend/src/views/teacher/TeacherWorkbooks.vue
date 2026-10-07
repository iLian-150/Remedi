<!-- 教师端：我的练习（v0.6.0 新增）——练习册知识库的书架式管理页。
     书架陈列：每本书站立在木质隔板上，封面 = PDF 第一页自动截取的封面图
     （接口 4.16 的 cover_url；无封面时用纯色书脊 + 竖排标题兜底）。
     每层最末尾留一个虚线「+」位添加书籍；点一本书弹出操作菜单：
     查看 PDF / 用它发布作业（跳发布页预选线下模式+该练习册）/ 删除（二次确认）。
     数据接口沿用练习册知识库 4.15 上传、4.16 列表、4.17 删除。 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>我的练习</h2>
      <p class="page-sub">把整本练习册 / 教材 PDF 放上书架，发布线下作业时直接从架上取用。封面会自动截取 PDF 的第一页。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="toast" class="ok-msg">{{ toast }}</div>
    <div v-if="loading" class="loading">正在整理书架…</div>

    <div v-else class="bookshelf">
      <div v-for="(shelf, si) in shelves" :key="si" class="shelf">
        <div class="shelf-books">
          <div v-for="w in shelf" :key="w.id" class="book-slot">
            <button class="book" :title="w.title" @click="openMenu(w)">
              <img v-if="w.cover_url" :src="w.cover_url" :alt="w.title" class="book-cover" />
              <span v-else class="book-spine" :style="{ background: spineColor(w.id) }">
                <span class="book-spine-title">{{ w.title }}</span>
              </span>
            </button>
            <div class="book-name">{{ w.title }}</div>
            <div class="book-date">{{ w.created_at.replace('T', ' ').slice(0, 10) }} 上架</div>
          </div>

          <!-- 每层末尾的空位：虚线「+」添加书籍（只在最后一层出现） -->
          <div v-if="si === shelves.length - 1" class="book-slot">
            <button class="book-add" @click="openUpload">
              <span class="book-add-plus">+</span>
              <span class="book-add-text">添加书籍</span>
            </button>
            <div class="book-name" style="color: var(--text-3)">上传 PDF</div>
          </div>
        </div>
        <div class="shelf-board"></div>
      </div>
      <p v-if="!workbooks.length" class="hint" style="margin-top: 14px">
        书架还是空的，点虚线框把第一本练习册放上来吧。
      </p>
    </div>

    <!-- 书籍操作菜单（轻量弹窗） -->
    <div v-if="menuBook" class="modal-mask" @click.self="menuBook = null">
      <div class="modal-card">
        <div class="modal-book-head">
          <img v-if="menuBook.cover_url" :src="menuBook.cover_url" :alt="menuBook.title" class="modal-cover" />
          <span v-else class="modal-spine" :style="{ background: spineColor(menuBook.id) }"></span>
          <div>
            <p class="modal-title">{{ menuBook.title }}</p>
            <p class="hint">{{ menuBook.created_at.replace('T', ' ').slice(0, 16) }} 上架</p>
          </div>
        </div>
        <div class="modal-actions">
          <a class="btn inline-icon" :href="menuBook.file_url" target="_blank" rel="noopener" style="text-decoration: none">
            <AppIcon name="file" :size="15" /> 查看 PDF
          </a>
          <button class="btn secondary inline-icon" @click="publishWith(menuBook)">
            <AppIcon name="plus-circle" :size="15" /> 用它发布作业
          </button>
          <button v-if="!confirmDelete" class="btn danger-outline inline-icon" @click="confirmDelete = true">
            <AppIcon name="trash" :size="15" /> 删除本书
          </button>
          <button v-else class="btn danger inline-icon" :disabled="deleting" @click="removeBook(menuBook)">
            <AppIcon name="trash" :size="15" /> {{ deleting ? '删除中…' : '确认删除？连 PDF 一起删' }}
          </button>
          <button class="btn ghost" @click="menuBook = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 添加书籍（上传弹窗） -->
    <div v-if="uploadOpen" class="modal-mask" @click.self="uploadOpen = false">
      <div class="modal-card">
        <p class="modal-title" style="margin-bottom: 12px">添加书籍</p>
        <input ref="fileRef" type="file" accept="application/pdf" hidden @change="onPickFile" />
        <button class="btn secondary inline-icon" @click="fileRef?.click()">
          <AppIcon name="file" :size="15" /> {{ pickedFile ? '重新选择 PDF' : '选择 PDF 文件' }}
        </button>
        <p v-if="pickedFile" class="hint" style="margin-top: 8px">
          已选：{{ pickedFile.name }}（{{ (pickedFile.size / 1024 / 1024).toFixed(1) }}MB，上限 30MB）
        </p>
        <div class="form-row" style="margin-top: 14px">
          <label>书名</label>
          <input v-model="uploadTitle" type="text" placeholder="默认取文件名，可以改" maxlength="128" />
        </div>
        <div class="modal-actions">
          <button class="btn" :disabled="!pickedFile || uploading" @click="doUpload">
            {{ uploading ? '上架中…' : '放上书架' }}
          </button>
          <button class="btn ghost" :disabled="uploading" @click="uploadOpen = false">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useTeacherStore } from '../../stores/teacher'
import type { Workbook } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'

const teacher = useTeacherStore()
const router = useRouter()

const workbooks = ref<Workbook[]>([])
const loading = ref(false)
const error = ref('')
const toast = ref('')

const SHELF_SIZE = 5
/** 书籍按层分组：每层 SHELF_SIZE 本；一本没有时也留一层空架放「+」位 */
const shelves = computed<Workbook[][]>(() => {
  const rows: Workbook[][] = []
  for (let i = 0; i < workbooks.value.length; i += SHELF_SIZE) {
    rows.push(workbooks.value.slice(i, i + SHELF_SIZE))
  }
  if (!rows.length) rows.push([])
  // 最后一层正好摆满时，再起一层空架专门放「+」位（右边空出的架）
  if (rows[rows.length - 1].length >= SHELF_SIZE) rows.push([])
  return rows
})

const SPINE_COLORS = ['#1D4ED8', '#0F766E', '#B45309', '#9D2449', '#5B5BD6', '#4B5563']
function spineColor(id: number): string {
  return SPINE_COLORS[Math.abs(id) % SPINE_COLORS.length]
}

function errMsg(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof d === 'string' ? d : fallback
}

function showToast(text: string) {
  toast.value = text
  setTimeout(() => {
    if (toast.value === text) toast.value = ''
  }, 2600)
}

// ---------- 书籍菜单 ----------
const menuBook = ref<Workbook | null>(null)
const confirmDelete = ref(false)
const deleting = ref(false)

function openMenu(w: Workbook) {
  menuBook.value = w
  confirmDelete.value = false
}

function publishWith(w: Workbook) {
  router.push({
    path: '/teacher/assignments/new',
    query: { mode: 'offline', workbook_id: String(w.id) }
  })
}

async function removeBook(w: Workbook) {
  deleting.value = true
  try {
    await teacher.deleteWorkbook(w.id)
    workbooks.value = workbooks.value.filter((x) => x.id !== w.id)
    menuBook.value = null
    showToast('已从书架删除')
  } catch (e) {
    error.value = '删除失败：' + errMsg(e, '请稍后重试。')
    console.error(e)
  } finally {
    deleting.value = false
    confirmDelete.value = false
  }
}

// ---------- 上传 ----------
const uploadOpen = ref(false)
const fileRef = ref<HTMLInputElement | null>(null)
const pickedFile = ref<File | null>(null)
const uploadTitle = ref('')
const uploading = ref(false)

function openUpload() {
  pickedFile.value = null
  uploadTitle.value = ''
  uploadOpen.value = true
}

function onPickFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
    error.value = '只支持 PDF 文件。'
    return
  }
  if (file.size > 30 * 1024 * 1024) {
    error.value = 'PDF 太大了（超过 30MB），请压缩后再传。'
    return
  }
  error.value = ''
  pickedFile.value = file
  if (!uploadTitle.value.trim()) {
    uploadTitle.value = file.name.replace(/\.pdf$/i, '')
  }
}

async function doUpload() {
  if (!pickedFile.value) return
  uploading.value = true
  error.value = ''
  try {
    // 后端标题取文件名：按老师填的书名重命名 File 再上传，不动接口
    const title = uploadTitle.value.trim()
    const file =
      title && title !== pickedFile.value.name.replace(/\.pdf$/i, '')
        ? new File([pickedFile.value], `${title}.pdf`, { type: 'application/pdf' })
        : pickedFile.value
    const wb = await teacher.uploadWorkbook(file)
    workbooks.value.unshift(wb)
    uploadOpen.value = false
    showToast('已放上书架')
  } catch (e) {
    error.value = '上传失败：' + errMsg(e, '请稍后重试。')
    console.error(e)
  } finally {
    uploading.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    workbooks.value = await teacher.fetchWorkbooks()
  } catch (e) {
    error.value = '书架加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
/* ---------- 书架 ---------- */
.bookshelf {
  background: linear-gradient(180deg, #FBFCFE 0%, #F4F6FA 100%);
  border: 1px solid #E4E9F2; border-radius: 16px;
  padding: 30px 30px 12px;
}
.shelf { margin-bottom: 30px; }
.shelf-books {
  display: flex; gap: 26px; align-items: flex-end; flex-wrap: wrap;
  padding: 0 10px;
  min-height: 158px;
}
.shelf-board {
  height: 13px; border-radius: 3px; margin-top: 2px;
  background: linear-gradient(180deg, #C89B6D 0%, #A97C50 55%, #8A5A33 100%);
  box-shadow: 0 10px 14px rgba(90, 58, 25, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.45);
}
.book-slot { width: 104px; text-align: center; }
.book {
  width: 104px; height: 140px; padding: 0; border: none; cursor: pointer;
  background: none; display: block; margin: 0 auto;
  transition: transform 0.25s ease;
}
.book:hover { transform: translateY(-7px); }
.book-cover {
  width: 104px; height: 140px; object-fit: cover; display: block;
  border-radius: 2px 7px 7px 2px;
  box-shadow:
    inset 4px 0 8px rgba(0, 0, 0, 0.18),
    0 6px 14px rgba(15, 23, 42, 0.22);
}
.book-spine {
  width: 104px; height: 140px; display: flex; align-items: center; justify-content: center;
  border-radius: 2px 7px 7px 2px;
  box-shadow:
    inset 4px 0 8px rgba(0, 0, 0, 0.22),
    inset -2px 0 4px rgba(255, 255, 255, 0.18),
    0 6px 14px rgba(15, 23, 42, 0.22);
}
.book-spine-title {
  writing-mode: vertical-rl; letter-spacing: 3px;
  color: #fff; font-size: 14px; font-weight: 700;
  max-height: 124px; overflow: hidden;
}
.book-name {
  margin-top: 8px; font-size: 13px; font-weight: 600; line-height: 1.35;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.book-date { font-size: 11.5px; color: var(--text-3); margin-top: 2px; }
.book-add {
  width: 104px; height: 140px; margin: 0 auto;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px;
  border: 2px dashed #B7C9F5; border-radius: 8px;
  background: rgba(255, 255, 255, 0.55); color: var(--primary);
  cursor: pointer; font-family: var(--font);
  transition: background 0.2s ease, border-color 0.2s ease, transform 0.25s ease;
}
.book-add:hover { background: var(--primary-50); border-color: var(--primary); transform: translateY(-4px); }
.book-add-plus { font-size: 34px; font-weight: 300; line-height: 1; }
.book-add-text { font-size: 13px; font-weight: 600; }

/* ---------- 弹窗 ---------- */
.modal-mask {
  position: fixed; inset: 0; z-index: 300;
  background: rgba(15, 23, 42, 0.42);
  display: flex; align-items: center; justify-content: center; padding: 20px;
}
.modal-card {
  width: min(480px, 100%);
  background: var(--card); border-radius: 16px; box-shadow: 0 24px 60px rgba(15, 23, 42, 0.3);
  padding: 22px;
  animation: modal-in 0.2s ease both;
}
@keyframes modal-in {
  from { opacity: 0; transform: translateY(8px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
.modal-book-head { display: flex; gap: 14px; align-items: center; margin-bottom: 16px; }
.modal-cover { width: 52px; height: 70px; object-fit: cover; border-radius: 2px 5px 5px 2px; box-shadow: 0 4px 10px rgba(15, 23, 42, 0.2); }
.modal-spine { width: 52px; height: 70px; border-radius: 2px 5px 5px 2px; flex-shrink: 0; box-shadow: inset 3px 0 6px rgba(0, 0, 0, 0.22); }
.modal-title { font-size: 16.5px; font-weight: 700; }
.modal-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; }
.modal-actions a.btn { text-decoration: none; }
.btn.danger-outline { background: #fff; color: var(--red); border: 1px solid #FECACA; }
.btn.danger-outline:hover { background: var(--red-bg); }
.btn.danger { background: var(--red); color: #fff; }
@media (prefers-reduced-motion: reduce) {
  .book, .book-add { transition: none; }
  .book:hover, .book-add:hover { transform: none; }
  .modal-card { animation: none; }
}
@media (max-width: 640px) {
  .bookshelf { padding: 20px 14px 8px; }
  .shelf-books { gap: 16px; }
}
</style>
