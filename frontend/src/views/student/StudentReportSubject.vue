<!-- 学生端：学习报告 · 科目详情（v0.6.0 从学习报告页拆出的独立页）
     入口：学习报告落地页点科目吊牌（播掉落动画后 router.push 到这里）；
     页头带「← 返回学习报告」按钮。
     本次改造（报告纯化）：本页只呈现数据——科目总览 + 知识点明细（四态徽标为只读
     状态，不带任何操作）；二次验证/变式题入口已移出报告，迁到订正页（订正成功后
     页内打开变式题面板；订正页便利贴墙上方另有「待验证的知识点」入口）。
     错题时间线已移入右侧栏（报告路由下右栏为「错题时间线」模式，点条目跳诊断
     详情页），本页不再内嵌时间线，避免双份。
     入场动画：卷轴铺开——内容自上而下裁剪展开，下轴杆随展开边缘同步下移后
     隐去；prefers-reduced-motion 时无动画。
     文案伦理：学生端用「待修复 / 反复出错 / 已订正待验证 / 已修复」，不出现「顽固」「置信度」。 -->
<template>
  <div class="page">
    <div class="page-head subject-head">
      <router-link to="/student/report" class="back-btn">
        <AppIcon name="chevron-left" :size="16" /> 返回学习报告
      </router-link>
      <h2>{{ subjectName }} · 学习报告</h2>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="!subj" class="card">
      <div class="empty">这个科目暂时还没有学习记录，先去作答几道题，报告就会慢慢长出来。</div>
    </div>

    <div v-else class="scroll-unroll">
      <div class="scroll-rod-top" aria-hidden="true"></div>

      <!-- 一级：科目总览 -->
      <div class="card">
        <h3><AppIcon name="book" :size="18" /> {{ subjectName }}总览</h3>
        <div class="stat-row">
          <div class="stat">
            <div class="stat-num tnum">{{ subj.submission_count }}</div>
            <div class="stat-label">累计提交</div>
          </div>
          <div class="stat green">
            <div class="stat-num tnum">{{ Math.round(subj.correct_rate * 100) }}%</div>
            <div class="stat-label">正确率</div>
          </div>
          <div class="stat amber">
            <div class="stat-num tnum">{{ subj.pending_fix_count }}</div>
            <div class="stat-label">待修复知识点</div>
          </div>
        </div>
        <div class="fix-progress">
          <div class="fix-progress-head">
            <span>知识修复进度</span>
            <span class="tnum">{{ Math.round(subj.fixed_ratio * 100) }}%</span>
          </div>
          <div class="fix-bar"><div :style="{ width: `${Math.round(subj.fixed_ratio * 100)}%` }"></div></div>
          <p class="hint">订正好错题、再做对一道同类题通过验证，才算真正修复——这里是已修复知识点占出过错知识点的比例。</p>
        </div>
      </div>

      <!-- 二级：知识点明细（纯数据呈现；逐条错题去右侧栏「错题时间线」看） -->
      <div class="card">
        <h3><AppIcon name="target" :size="18" /> 知识点明细</h3>
        <p class="card-sub">按错误率从高到低排。每个知识点错过几次、现在是什么状态都写在这里；想逐条翻错题，打开右侧栏的「错题时间线」。</p>
        <div v-if="!subj.knowledge_points.length" class="empty">这个科目暂时没有错题记录，继续保持。</div>
        <div v-for="kp in subj.knowledge_points" :key="kp.name" class="kp-block">
          <div class="kp-row">
            <div class="kp-main">
              <span class="kp-name">{{ kp.name }}</span>
              <span class="kp-meta">
                出错 <span class="tnum">{{ kp.error_count }}</span> 次 · 提交 <span class="tnum">{{ kp.attempts }}</span> 次
                <template v-if="kp.last_error_at"> · 最近出错 {{ fmtDate(kp.last_error_at) }}</template>
              </span>
              <span class="kp-bar"><span :style="{ width: `${Math.round(kp.error_rate * 100)}%` }"></span></span>
            </div>
            <span :class="`badge ${STATUS_BADGE[kp.status]}`">{{ STATUS_TEXT[kp.status] }}</span>
            <span class="kp-rate tnum">{{ Math.round(kp.error_rate * 100) }}%</span>
          </div>
        </div>
      </div>

      <div class="scroll-rod-bottom" aria-hidden="true"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useStudentStore } from '../../stores/student'
import type { KnowledgePointStatus, SubjectReport } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'

const student = useStudentStore()
const route = useRoute()

const SUBJECT_TEXT: Record<string, string> = { math: '数学', english: '英语', physics: '物理', chemistry: '化学' }
// v0.4.0 四态文案（只读状态呈现）：fixed 专指「订正 + 通过二次验证」，与后端新口径一致
const STATUS_TEXT: Record<KnowledgePointStatus, string> = {
  pending: '待修复',
  stubborn: '反复出错',
  awaiting_verify: '已订正待验证',
  fixed: '已修复'
}
const STATUS_BADGE: Record<KnowledgePointStatus, string> = {
  pending: 'badge-amber',
  stubborn: 'badge-red',
  awaiting_verify: 'badge-blue',
  fixed: 'badge-green'
}

const subject = computed(() => String(route.params.subject || 'math'))
const subjectName = computed(() => SUBJECT_TEXT[subject.value] ?? subject.value)

const report = ref<SubjectReport[]>([])
const loading = ref(false)
const error = ref('')

const subj = computed<SubjectReport | null>(
  () => report.value.find((r) => r.subject === subject.value) ?? null
)

function fmtDate(t: string): string {
  return t.replace('T', ' ').slice(0, 10)
}

onMounted(async () => {
  loading.value = true
  try {
    report.value = await student.fetchReport()
  } catch (e) {
    error.value = '学习报告加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.subject-head h2 { margin-top: 10px; }
.back-btn {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 13.5px; font-weight: 600; color: var(--primary);
  text-decoration: none; padding: 6px 12px 6px 8px;
  border: 1px solid #D7E3FA; border-radius: 999px; background: var(--primary-50);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.back-btn:hover { transform: translateY(-1px); box-shadow: var(--shadow); }

/* 入场：卷轴铺开——内容自上而下裁剪展开，下轴杆随展开边缘同步下移、到位后隐去 */
.scroll-unroll {
  position: relative;
  animation: scroll-open 0.6s cubic-bezier(0.22, 0.8, 0.36, 1) both;
}
@keyframes scroll-open {
  0% { clip-path: inset(-14px -10px 100% -10px); opacity: 0.35; }
  100% { clip-path: inset(-14px -10px -14px -10px); opacity: 1; }
}
.scroll-rod-top {
  position: relative;
  height: 12px; border-radius: 6px;
  margin: 0 -4px 16px;
  background: linear-gradient(180deg, #DCC49C 0%, #B9906A 55%, #9A7648 100%);
  box-shadow: 0 2px 5px rgba(96, 68, 32, 0.35);
}
.scroll-rod-top::before,
.scroll-rod-top::after {
  content: '';
  position: absolute; top: 50%;
  width: 18px; height: 18px; border-radius: 50%;
  transform: translateY(-50%);
  background: radial-gradient(circle at 35% 35%, #C8A06C, #8A683C);
  box-shadow: 0 1px 3px rgba(96, 68, 32, 0.4);
}
.scroll-rod-top::before { left: -7px; }
.scroll-rod-top::after { right: -7px; }
.scroll-rod-bottom {
  position: absolute; left: -4px; right: -4px;
  height: 12px; border-radius: 6px;
  background: linear-gradient(180deg, #DCC49C 0%, #B9906A 55%, #9A7648 100%);
  box-shadow: 0 2px 5px rgba(96, 68, 32, 0.35);
  pointer-events: none;
  animation: scroll-rod-travel 0.6s cubic-bezier(0.22, 0.8, 0.36, 1) both;
}
@keyframes scroll-rod-travel {
  0% { top: 0; opacity: 1; }
  82% { opacity: 1; }
  100% { top: calc(100% - 12px); opacity: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .scroll-unroll { animation: none; }
  .scroll-rod-bottom { display: none; }
  .back-btn { transition: none; }
}

.fix-progress { margin-top: 16px; }
.fix-progress-head { display: flex; justify-content: space-between; font-size: 13.5px; font-weight: 600; margin-bottom: 6px; }
.fix-bar { height: 10px; background: #EDF0F4; border-radius: 5px; overflow: hidden; }
.fix-bar > div { height: 100%; background: var(--green); border-radius: 5px; transition: width 0.3s; }
.fix-progress .hint { margin-top: 6px }

/* ---------- 知识点明细（只读行） ---------- */
.kp-block { border-bottom: 1px solid #F1F3F6; }
.kp-block:last-child { border-bottom: none; }
.kp-row {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 4px;
}
.kp-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.kp-name { font-size: 15px; font-weight: 600; }
.kp-meta { font-size: 12.5px; color: var(--text-2); }
.kp-bar { display: block; height: 6px; background: #EDF0F4; border-radius: 3px; overflow: hidden; max-width: 340px; }
.kp-bar > span { display: block; height: 100%; background: var(--amber); border-radius: 3px; }
.kp-rate { font-size: 15px; font-weight: 700; color: var(--amber); min-width: 44px; text-align: right; }
</style>
