<!-- 教师端：教学建议（新增页）
     基于轻量错误摘要与现有看板接口生成分层辅导建议和课堂讲评建议。
     在前端用规则模板生成分层辅导建议与课堂讲评建议。
     页面明确注明「规则模板生成，待二期接模型」。 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>教学建议</h2>
      <p class="page-sub">根据班级错误数据自动生成的辅导与讲评参考。</p>
      <nav class="workflow-tabs" aria-label="教学工作区">
        <router-link to="/teacher/dashboard" class="workflow-tab">总览</router-link>
        <router-link to="/teacher/suggestions" class="workflow-tab">教学建议</router-link>
      </nav>
    </div>

    <div class="note-box">
      本页建议由前端规则模板生成，仅供参考；待二期接入模型后升级为个性化智能建议。
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">正在生成建议…</div>

    <template v-if="!loading && ready">
      <!-- 分层辅导建议 -->
      <div class="card">
        <h3><AppIcon name="target" :size="18" /> 分层辅导建议</h3>

        <h4 class="section-title">重点一对一：顽固误区学生</h4>
        <div v-if="oneOnOne.length">
          <div v-for="s in oneOnOne" :key="s.studentId" class="suggest-block" style="border-left-color: var(--red)">
            <h4>
              <router-link :to="`/teacher/students/${s.studentId}`" style="color: var(--primary)">{{ s.studentName }}</router-link>
              <span class="badge badge-red tnum" style="margin-left: 8px">{{ s.count }} 个顽固误区</span>
            </h4>
            <ul>
              <li v-for="kp in s.knowledgePoints" :key="kp">「{{ kp }}」反复出错，建议一对一当面诊断其思维过程</li>
            </ul>
          </div>
        </div>
        <p v-else class="hint">暂无顽固误区学生，继续保持。</p>

        <h4 class="section-title">课堂统一提醒：偶发失误集中的知识点</h4>
        <div v-if="classReminders.length">
          <div v-for="k in classReminders" :key="k.knowledge_point" class="suggest-block" style="border-left-color: var(--amber)">
            <h4>「{{ k.knowledge_point }}」 <span class="badge badge-amber tnum" style="margin-left: 8px">错误率 {{ Math.round(k.error_rate * 100) }}%</span></h4>
            <p>{{ k.total }} 次错误均为偶发失误，无顽固误区。建议课堂上统一提醒检查要点，不必逐个约谈。</p>
          </div>
        </div>
        <p v-else class="hint">暂无符合条件的知识点。</p>

        <h4 class="section-title">继续保持：表现稳定的学生</h4>
        <div v-if="steadyStudents.length">
          <div class="suggest-block" style="border-left-color: var(--green)">
            <p>
              <template v-for="(s, i) in steadyStudents" :key="s.id">
                <router-link :to="`/teacher/students/${s.id}`" style="color: var(--primary); font-weight: 600">{{ s.name }}</router-link>{{ i < steadyStudents.length - 1 ? '、' : '' }}
              </template>
              等 {{ steadyStudents.length }} 名学生已提交且暂无错误记录，建议布置拓展题保持手感。
            </p>
          </div>
        </div>
        <p v-else class="hint">暂无符合条件的学生。</p>
      </div>

      <!-- 课堂讲评建议 -->
      <div class="card">
        <h3><AppIcon name="megaphone" :size="18" /> 课堂讲评建议</h3>
        <p class="card-sub">按高频错题排序的讲评重点清单，建议按顺序分配讲评时间。</p>
        <div v-if="reviewPlan.length">
          <div v-for="(r, i) in reviewPlan" :key="r.question_id" class="suggest-block">
            <h4>
              <span class="badge badge-blue tnum">第 {{ i + 1 }} 讲</span>
              {{ r.stem }}
            </h4>
            <p>
              <span class="badge badge-blue">{{ r.knowledge_point }}</span>
              <span class="tnum" style="font-size: 13px; color: var(--text-2)">错误 {{ r.error_count }} 次 · {{ r.student_count }} 名学生</span>
            </p>
            <p style="margin-top: 8px"><strong>讲评要点：</strong>{{ r.advice }}</p>
          </div>
        </div>
        <div v-else class="empty">暂无高频错题数据。</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useTeacherStore } from '../../stores/teacher'
import type { KnowledgePointStat, StudentSummary, TeacherErrorSummary, TopQuestion } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'

const teacher = useTeacherStore()

const loading = ref(false)
const error = ref('')
const ready = ref(false)

const errors = ref<TeacherErrorSummary[]>([])
const topQuestions = ref<TopQuestion[]>([])
const kpStats = ref<KnowledgePointStat[]>([])
const steadyStudents = ref<StudentSummary[]>([])

// ---------- 分层辅导：重点一对一（顽固误区学生名单） ----------
interface OneOnOne {
  studentId: number
  studentName: string
  count: number
  knowledgePoints: string[]
}
const oneOnOne = computed<OneOnOne[]>(() => {
  const map = new Map<number, { name: string; kps: Set<string>; count: number }>()
  errors.value
    .filter((e) => e.is_stubborn)
    .forEach((e) => {
      const cur = map.get(e.student.id) ?? { name: e.student.name, kps: new Set<string>(), count: 0 }
      cur.kps.add(e.knowledge_point)
      cur.count += 1
      map.set(e.student.id, cur)
    })
  return [...map.entries()]
    .map(([studentId, v]) => ({ studentId, studentName: v.name, count: v.count, knowledgePoints: [...v.kps] }))
    .sort((a, b) => b.count - a.count)
})

// ---------- 分层辅导：课堂统一提醒（偶发失误集中、无顽固的知识点） ----------
interface ClassReminder extends KnowledgePointStat {
  total: number
}
const classReminders = computed<ClassReminder[]>(() => {
  const byKp = new Map<string, { total: number; stubborn: number }>()
  errors.value.forEach((e) => {
    const cur = byKp.get(e.knowledge_point) ?? { total: 0, stubborn: 0 }
    cur.total += 1
    if (e.is_stubborn) cur.stubborn += 1
    byKp.set(e.knowledge_point, cur)
  })
  // 知识点排行接口已按错误率降序，过滤和映射会保留原有顺序。
  return kpStats.value
    .filter((k) => {
      const s = byKp.get(k.knowledge_point)
      return k.error_rate >= 0.3 && s && s.total >= 2 && s.stubborn === 0
    })
    .map((k) => ({ ...k, total: byKp.get(k.knowledge_point)?.total ?? 0 }))
})

// ---------- 分层辅导：表现稳定 ----------
// ---------- 课堂讲评：按高频错题排序的讲评重点 ----------
const TYPE_ADVICE: Record<string, string> = {
  '概念混淆': '主要错因是概念混淆，建议从概念辨析入手，板书对比易混点，再配 2 道变式题巩固。',
  '计算失误': '主要错因是计算失误，建议课堂统一提醒检查步骤，可布置 5 分钟限时小练。',
  '审题遗漏': '主要错因是审题遗漏，建议带领学生圈画题干关键词，训练「慢审题、快答题」的习惯。',
  '无法解析': '部分作答无法解析，建议先确认学生作答格式是否规范，再逐个核对思路。'
}

interface ReviewItem extends TopQuestion {
  advice: string
}
const reviewPlan = computed<ReviewItem[]>(() => {
  const byQ = new Map<number, Map<string, number>>()
  errors.value.forEach((e) => {
    const m = byQ.get(e.question.id) ?? new Map<string, number>()
    m.set(e.error_type, (m.get(e.error_type) ?? 0) + 1)
    byQ.set(e.question.id, m)
  })
  // 高频错题接口已按错误数降序并以题目 ID 稳定排序，直接沿用。
  return topQuestions.value.map((q) => {
    const dist = byQ.get(q.question_id)
    let advice = '建议结合课堂观察补充讲评要点。'
    if (dist && dist.size) {
      const [topType, topCount] = [...dist.entries()].sort((a, b) => b[1] - a[1])[0]
      const total = [...dist.values()].reduce((s, n) => s + n, 0)
      const pct = Math.round((topCount / total) * 100)
      const base = TYPE_ADVICE[topType] ?? '建议针对该错因设计专项讲解。'
      advice = `样本中「${topType}」占比约 ${pct}%。${base}`
    }
    return { ...q, advice }
  })
})

onMounted(async () => {
  loading.value = true
  try {
    const [errItems, tq, kp, stu] = await Promise.all([
      teacher.fetchRecentErrorSummaries(100),
      teacher.fetchTopQuestions(10),
      teacher.fetchKnowledgePoints(),
      teacher.fetchStudents(true)
    ])
    errors.value = errItems
    topQuestions.value = tq
    kpStats.value = kp
    steadyStudents.value = stu
    ready.value = true
  } catch (e) {
    error.value = '教学建议生成失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.section-title { font-size: 15px; margin: 18px 0 10px; }
.section-title:first-of-type { margin-top: 4px; }
</style>
