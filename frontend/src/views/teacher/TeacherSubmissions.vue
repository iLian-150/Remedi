<!-- 教师端：批改列表
     说明：契约未提供教师端的提交列表接口，批改列表按 error 记录列表（4.1）实现，
     每条记录 = 一次"出错"的诊断，包含学生/题目/步骤/错因，支持过滤与分页。 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>批改纠错</h2>
      <p class="page-sub">每条记录都是一次 AI 诊断；分类存疑的可以在详情页一键纠错，回标数据会入库用于模型优化。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>

    <div class="card">
      <div class="toolbar">
        <label style="font-size: 14px; color: var(--text-2)">知识点：</label>
        <input v-model="filter.knowledge_point" type="text" placeholder="如：一元一次方程" style="width: 180px" />
        <label style="font-size: 14px; color: var(--text-2)">错因：</label>
        <select v-model="filter.error_type" style="width: auto">
          <option value="">全部</option>
          <option v-for="t in ERROR_TYPES" :key="t" :value="t">{{ t }}</option>
        </select>
        <label style="font-size: 14px; color: var(--text-2)">
          <input type="checkbox" v-model="filter.stubborn_only" style="width: auto" /> 只看顽固误区
        </label>
        <button class="btn small" @click="load(0)">查询</button>
      </div>

      <div v-if="loading" class="loading">加载中…</div>
      <table class="table" v-else-if="items.length">
        <thead>
          <tr><th>学生</th><th>题目</th><th>出错步骤</th><th>错因</th><th>置信度</th><th>性质</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="e in items" :key="e.id">
            <td>
              <router-link :to="`/teacher/students/${e.student.id}`" style="color: var(--primary); font-weight: 600">
                {{ e.student.name }}
              </router-link>
            </td>
            <td>{{ e.question.stem }}</td>
            <td>{{ e.step_text }}</td>
            <td>
              <ErrorTypeBadge :type="e.error_type" />
              <span v-if="e.teacher_corrected" class="badge badge-gray">已纠错</span>
            </td>
            <td class="num tnum">{{ Math.round(e.confidence * 100) }}%</td>
            <td>
              <span class="badge" :class="e.is_stubborn ? 'badge-red' : 'badge-green'">
                {{ e.is_stubborn ? '顽固' : '偶发' }}
              </span>
            </td>
            <td>
              <router-link :to="`/teacher/submissions/${e.id}`"><button class="btn small">诊断详情</button></router-link>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">暂无错误记录。</div>

      <div class="pagination" v-if="total > pageSize">
        <button class="btn small secondary" :disabled="offset === 0" @click="load(offset - pageSize)">上一页</button>
        <span style="font-size: 13px; color: var(--text-3)" class="tnum">共 {{ total }} 条</span>
        <button class="btn small secondary" :disabled="offset + pageSize >= total" @click="load(offset + pageSize)">下一页</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useTeacherStore } from '../../stores/teacher'
import type { TeacherErrorItem } from '../../api/types'
import { ERROR_TYPES } from '../../api/types'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'

const teacher = useTeacherStore()

const items = ref<TeacherErrorItem[]>([])
const total = ref(0)
const offset = ref(0)
const pageSize = 20
const loading = ref(false)
const error = ref('')

const filter = reactive({
  knowledge_point: '',
  error_type: '',
  stubborn_only: false
})

async function load(newOffset: number) {
  offset.value = newOffset
  loading.value = true
  error.value = ''
  try {
    const res = await teacher.fetchErrors({
      knowledge_point: filter.knowledge_point.trim() || undefined,
      error_type: filter.error_type || undefined,
      stubborn_only: filter.stubborn_only || undefined,
      limit: pageSize,
      offset: offset.value
    })
    items.value = res.items
    total.value = res.total
  } catch (e) {
    error.value = '批改列表加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => load(0))
</script>

<style scoped>
.pagination { display: flex; gap: 12px; align-items: center; justify-content: center; margin-top: 16px; }
</style>
