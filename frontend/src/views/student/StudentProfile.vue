<!-- 学生端：我的档案（v0.9.0 黑板化重做，数据与接口不变）
     主体是一块大黑板：木框 + 黑板绿板面，个人信息、学习数据、知识点掌握度
     全部用「粉笔字」写在板上（楷体字栈 + 粉笔晕染阴影，重点数字用粉笔黄/粉笔粉点缀，
     掌握度是粉笔横条 + 虚线刻度）；老师的建议是板下角的粉笔「老师寄语」。
     板下方走校园化：已订正的错题做成「奖状」小卡（米色纸 + 红边 + 印章圆标）陈列成
     奖状墙；错误轨迹改成课表式网格的「成长记录表」；问题类型分布保留图表卡。
     文案伦理：学生端用「需要加固的知识点」「已订正」「继续保持」，不出现贴标签术语；
     「已订正」口径 = 本机提交订正且判定正确；知识点「已修复」以学习报告为准。 -->
<template>
  <div class="page">
    <div class="page-head">
      <h2>我的档案</h2>
      <p class="page-sub">记录你的每一次进步：错过的知识点，一个一个修复。</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-if="profile">
      <!-- ================= 大黑板 ================= -->
      <section class="board-frame">
        <div class="board">
          <div class="board-head">
            <span class="board-title chalk">
              <AppIcon name="cap" :size="19" /> 我的学习档案
            </span>
            <span class="board-class chalk-dim">Remedi 学习档案 · 黑板报</span>
          </div>

          <div class="board-identity">
            <div class="chalk-name chalk">{{ profile.student.name }}</div>
            <p class="chalk-meta chalk-dim">
              学号 <span class="chalk tnum">{{ profile.student.student_no || '—' }}</span>
              · 身份 学生
              <template v-if="profile.student.created_at">
                · {{ fmtDate(profile.student.created_at) }} 来到 Remedi
              </template>
            </p>
          </div>

          <div class="chalk-divider"></div>

          <!-- 黑板上的学习数据（粉笔数字） -->
          <div class="board-stats">
            <div class="board-stat">
              <div class="board-stat-num chalk tnum">{{ totalAttempts }}</div>
              <div class="board-stat-label chalk-dim">累计作答</div>
            </div>
            <div class="board-stat">
              <div class="board-stat-num chalk tnum">{{ totalErrors }}</div>
              <div class="board-stat-label chalk-dim">累计发现问题</div>
            </div>
            <div class="board-stat">
              <div class="board-stat-num chalk chalk-yellow tnum">{{ reinforcingCount }}</div>
              <div class="board-stat-label chalk-dim">加固中</div>
            </div>
            <div class="board-stat">
              <div class="board-stat-num chalk chalk-green tnum">{{ fixedIds.size }}</div>
              <div class="board-stat-label chalk-dim">已订正错题</div>
            </div>
          </div>

          <!-- 知识点掌握度：粉笔条 -->
          <div class="board-mastery" v-if="profile.knowledge_points.length">
            <p class="board-section-title chalk">知识点掌握度 <span class="chalk-dim board-section-sub">—— 粉笔条越长，掌握得越牢</span></p>
            <div v-for="k in profile.knowledge_points" :key="k.knowledge_point" class="chalk-row">
              <span class="chalk-kp chalk">{{ k.knowledge_point }}</span>
              <span class="chalk-track">
                <span
                  class="chalk-fill"
                  :class="masteryTone(k.mastery)"
                  :style="{ width: `${Math.max(4, Math.round(k.mastery * 100))}%` }"
                ></span>
                <span class="chalk-ticks"></span>
              </span>
              <span class="chalk-pct chalk tnum">{{ Math.round(k.mastery * 100) }}%</span>
            </div>
          </div>
          <p v-else class="chalk-dim board-empty">还没有作答记录，去完成第一份作业，这里就会写满你的进步啦。</p>

          <!-- 老师寄语（粉笔手写在板角） -->
          <div class="board-message" v-if="profile.suggestion">
            <p class="board-message-label chalk chalk-pink">老师寄语</p>
            <p class="chalk board-message-text">{{ sanitizeStudentCopy(profile.suggestion) }}</p>
          </div>

          <!-- 板面装饰：粉笔与板擦（纯 CSS） -->
          <div class="board-ledge" aria-hidden="true">
            <span class="chalk-stick"></span>
            <span class="chalk-stick short"></span>
            <span class="board-eraser"></span>
          </div>
        </div>
      </section>

      <!-- ================= 奖状墙 ================= -->
      <div class="card">
        <h3><AppIcon name="sparkles" :size="17" /> 我的奖状墙</h3>
        <p class="card-sub">每订正对一道错题，就有一张小奖状。攒满它们，知识点就真正属于你了。</p>
        <div v-if="certificates.length" class="cert-grid">
          <div v-for="e in certificates" :key="e.id" class="cert">
            <p class="cert-head">奖 状</p>
            <p class="cert-body">
              <strong>{{ profile.student.name }}</strong> 同学<br />
              已订正「{{ e.knowledge_point }}」的错题
            </p>
            <p class="cert-foot tnum">{{ fmtTime(e.created_at) }} 出错 · 已订正</p>
            <span class="cert-seal">已订正</span>
          </div>
        </div>
        <div v-else class="empty">还没有奖状——去订正页做对第一道错题，第一张奖状就是你的。</div>
      </div>

      <!-- ================= 成长记录表（课表式网格） ================= -->
      <div class="card">
        <h3>成长记录表</h3>
        <p class="card-sub">像课程表一样排下来的错误轨迹：先订正，再去学习报告做一道同类题验证，知识点就真正修复了。</p>
        <div v-if="timeline.length" class="record-wrap">
          <table class="record-table">
            <thead>
              <tr><th>时间</th><th>知识点</th><th>问题类型</th><th>出错的步骤</th><th>状态</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="e in timeline" :key="e.id">
                <td class="tnum record-time">{{ fmtTime(e.created_at) }}</td>
                <td><span class="badge badge-blue">{{ e.knowledge_point }}</span></td>
                <td><ErrorTypeBadge :type="e.error_type" /></td>
                <td class="record-step">{{ e.step_text }}</td>
                <td>
                  <span v-if="fixedIds.has(e.id)" class="badge badge-green">已订正</span>
                  <span v-else class="badge badge-amber">加固中</span>
                </td>
                <td>
                  <router-link v-if="!fixedIds.has(e.id)" to="/student/corrections">
                    <button class="btn small ghost inline-icon">去订正 <AppIcon name="chevron-right" :size="14" /></button>
                  </router-link>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty">还没有错误记录，继续保持！</div>
      </div>

      <!-- 问题类型分布 -->
      <div class="card">
        <h3>问题类型分布</h3>
        <p class="card-sub">看看你的问题主要出在哪一类，对症练习最有效。</p>
        <EChart v-if="typeOptionData.length" :option="typeOption" />
        <div v-else class="empty">暂无数据。</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useStudentStore } from '../../stores/student'
import { useAuthStore } from '../../stores/auth'
import type { StudentProfile } from '../../api/types'
import { errorTypePalette, sanitizeStudentCopy } from '../../utils/errorType'
import { getFixedErrorIds } from '../../utils/correctionTracker'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import { AsyncEChartPie as EChart } from '../../components/AsyncEChart'
import AppIcon from '../../components/icons/AppIcon.vue'

const student = useStudentStore()
const auth = useAuthStore()
const profile = ref<StudentProfile | null>(null)
const loading = ref(false)
const error = ref('')
const fixedIds = ref<Set<number>>(new Set())
type ProfileErrorRecord = StudentProfile['stubborn_errors'][number] | StudentProfile['recent_errors'][number]

// 一次汇总档案页的总量、去重时间线、奖状与问题类型，避免模板分别重复扫描。
const profileSummary = computed(() => {
  let totalAttempts = 0
  let totalErrors = 0
  for (const item of profile.value?.knowledge_points ?? []) {
    totalAttempts += item.attempts
    totalErrors += item.errors
  }

  // 最近错误沿用原优先级：同 ID 时覆盖顽固错误列表中的记录。
  const map = new Map<number, ProfileErrorRecord>()
  for (const item of profile.value?.stubborn_errors ?? []) map.set(item.id, item)
  for (const item of profile.value?.recent_errors ?? []) map.set(item.id, item)
  const timeline = [...map.values()].sort((a, b) => b.created_at.localeCompare(a.created_at))

  const certificates: ProfileErrorRecord[] = []
  const typeCounts = new Map<string, number>()
  let reinforcingCount = 0
  for (const item of timeline) {
    if (fixedIds.value.has(item.id)) certificates.push(item)
    else reinforcingCount++
    typeCounts.set(item.error_type, (typeCounts.get(item.error_type) ?? 0) + 1)
  }

  return {
    totalAttempts,
    totalErrors,
    timeline,
    certificates,
    reinforcingCount,
    typeOptionData: [...typeCounts.entries()].map(([name, value]) => ({ name, value })),
  }
})
const totalAttempts = computed(() => profileSummary.value.totalAttempts)
const totalErrors = computed(() => profileSummary.value.totalErrors)
const timeline = computed(() => profileSummary.value.timeline)
const reinforcingCount = computed(() => profileSummary.value.reinforcingCount)

// 奖状墙：已订正的错题（轨迹 ∩ 本机已订正集）
const certificates = computed(() => profileSummary.value.certificates)

// 问题类型分布：三色统一
const typeOptionData = computed(() => profileSummary.value.typeOptionData)

const typeOption = computed(() => ({
  tooltip: { trigger: 'item', valueFormatter: (v: number) => `${v} 次` },
  color: errorTypePalette(),
  series: [
    {
      type: 'pie',
      radius: '62%',
      data: typeOptionData.value,
      label: { color: '#4B5563' },
      itemStyle: { borderColor: '#fff', borderWidth: 2 }
    }
  ]
}))

/** 粉笔条颜色：掌握度高=粉笔绿、中=粉笔白、低=粉笔粉 */
function masteryTone(mastery: number): string {
  if (mastery >= 0.8) return 'tone-green'
  if (mastery >= 0.5) return 'tone-white'
  return 'tone-pink'
}

function fmtTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}
function fmtDate(t: string): string {
  return t.replace('T', ' ').slice(0, 10)
}

onMounted(async () => {
  loading.value = true
  try {
    if (auth.user) fixedIds.value = getFixedErrorIds(auth.user.id)
    profile.value = await student.fetchProfile()
  } catch (e) {
    error.value = '档案加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
/* ================= 大黑板 ================= */
.board-frame {
  /* 木质边框：多层渐变模拟木纹 + 外阴影 */
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.14), rgba(0, 0, 0, 0.12)),
    repeating-linear-gradient(93deg, #8A5A33 0 46px, #96683D 46px 52px, #7C4F2A 52px 104px);
  border-radius: 18px;
  padding: 14px;
  box-shadow: var(--shadow-lg), inset 0 2px 3px rgba(255, 255, 255, 0.25), inset 0 -3px 6px rgba(0, 0, 0, 0.3);
  margin-bottom: 16px;
}
.board {
  position: relative;
  /* 黑板绿板面：径向微光 + 斜向擦痕感 */
  background:
    radial-gradient(120% 90% at 30% 0%, rgba(255, 255, 255, 0.07), transparent 55%),
    repeating-linear-gradient(115deg, rgba(255, 255, 255, 0.016) 0 26px, transparent 26px 52px),
    linear-gradient(160deg, #33584A 0%, #2E4B3F 55%, #29473B 100%);
  border-radius: 10px;
  padding: 26px 30px 20px;
  box-shadow: inset 0 0 42px rgba(0, 0, 0, 0.35), inset 0 2px 8px rgba(0, 0, 0, 0.3);
  overflow: hidden;
}
/* 粉笔字：楷体字栈 + 轻微晕染 */
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
.chalk-pink { color: #FFB7C5; text-shadow: 0 0 1px rgba(255, 183, 197, 0.6), 0 0 8px rgba(255, 183, 197, 0.2); }

.board-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.board-title { font-size: 17px; font-weight: 700; display: inline-flex; align-items: center; gap: 8px; }
.board-title :deep(svg) { filter: drop-shadow(0 0 3px rgba(247, 243, 232, 0.35)); }
.board-class { font-size: 13px; }
.board-identity { margin-top: 16px; }
.chalk-name { font-size: 38px; font-weight: 700; line-height: 1.15; }
.chalk-meta { margin-top: 6px; font-size: 15px; }
/* 粉笔分隔线：断续虚线像手划的 */
.chalk-divider {
  height: 0;
  border-top: 2px dashed rgba(247, 243, 232, 0.4);
  margin: 18px 0 4px;
  transform: rotate(-0.15deg);
}
.board-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 14px; }
.board-stat { text-align: left; }
.board-stat-num { font-size: 34px; font-weight: 700; line-height: 1.1; }
.board-stat-label { font-size: 13.5px; margin-top: 2px; }

.board-mastery { margin-top: 20px; }
.board-section-title { font-size: 16.5px; font-weight: 700; margin-bottom: 10px; }
.board-section-sub { font-size: 13px; font-weight: 400; }
.chalk-row { display: flex; align-items: center; gap: 12px; margin-bottom: 9px; }
.chalk-kp { flex: 0 0 118px; font-size: 15px; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chalk-track {
  position: relative; flex: 1; height: 17px;
  border: 2px solid rgba(247, 243, 232, 0.5);
  /* 手绘感：不对称圆角 */
  border-radius: 255px 14px 225px 14px / 14px 225px 14px 255px;
  overflow: hidden;
}
.chalk-fill {
  position: absolute; inset: 1px auto 1px 1px;
  border-radius: inherit;
  /* 粉笔填充：斜纹理 + 不均匀透明 */
  background:
    repeating-linear-gradient(100deg, rgba(255, 255, 255, 0.16) 0 7px, transparent 7px 13px),
    rgba(247, 243, 232, 0.92);
  transition: width 0.5s ease;
}
.chalk-fill.tone-green { background: repeating-linear-gradient(100deg, rgba(255, 255, 255, 0.16) 0 7px, transparent 7px 13px), rgba(181, 231, 160, 0.92); }
.chalk-fill.tone-pink { background: repeating-linear-gradient(100deg, rgba(255, 255, 255, 0.16) 0 7px, transparent 7px 13px), rgba(255, 183, 197, 0.92); }
/* 虚线刻度（25/50/75） */
.chalk-ticks {
  position: absolute; inset: 0;
  background:
    linear-gradient(90deg, transparent calc(25% - 1px), rgba(20, 40, 32, 0.45) 25%, transparent calc(25% + 1px)),
    linear-gradient(90deg, transparent calc(50% - 1px), rgba(20, 40, 32, 0.45) 50%, transparent calc(50% + 1px)),
    linear-gradient(90deg, transparent calc(75% - 1px), rgba(20, 40, 32, 0.45) 75%, transparent calc(75% + 1px));
}
.chalk-pct { flex: 0 0 46px; font-size: 15px; }
.board-empty { margin-top: 16px; font-size: 15px; }

.board-message { margin-top: 18px; max-width: 640px; transform: rotate(-0.3deg); }
.board-message-label { font-size: 14px; font-weight: 700; margin-bottom: 3px; }
.board-message-text { font-size: 16.5px; line-height: 1.75; }

/* 板面底部小托边：粉笔 + 板擦 */
.board-ledge { display: flex; align-items: flex-end; gap: 8px; margin-top: 18px; }
.chalk-stick {
  width: 44px; height: 7px; border-radius: 4px;
  background: linear-gradient(180deg, #FFFFFF, #E9E4D2);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35);
  transform: rotate(-2deg);
}
.chalk-stick.short { width: 26px; transform: rotate(1.5deg); background: linear-gradient(180deg, #FFE58A, #F3D97B); }
.board-eraser {
  margin-left: auto;
  width: 56px; height: 15px; border-radius: 3px;
  background: linear-gradient(180deg, #B08954 0 55%, #4B4B4B 55% 100%);
  box-shadow: 0 2px 3px rgba(0, 0, 0, 0.4);
  transform: rotate(-1deg);
}

@media (max-width: 720px) {
  .board-frame { padding: 9px; border-radius: 14px; }
  .board { padding: 20px 18px 16px; }
  .chalk-name { font-size: 31px; }
  .board-stats { grid-template-columns: repeat(2, 1fr); }
  .board-stat-num { font-size: 29px; }
  .chalk-kp { flex-basis: 92px; font-size: 14px; }
}
@media (prefers-reduced-motion: reduce) {
  .chalk-fill { transition: none; }
}

/* ================= 奖状墙 ================= */
.cert-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 14px; }
.cert {
  position: relative;
  background: linear-gradient(165deg, #FFFBEB, #FFF6DA);
  border: 2px solid #DC2626;
  outline: 1px solid rgba(220, 38, 38, 0.45);
  outline-offset: -7px;
  border-radius: 6px;
  padding: 18px 18px 14px;
  text-align: center;
  box-shadow: var(--shadow);
  overflow: hidden;
}
.cert-head {
  font-family: 'KaiTi', 'STKaiti', 'Kaiti SC', serif;
  font-size: 21px; font-weight: 700; letter-spacing: 10px; text-indent: 10px;
  color: #B91C1C;
}
.cert-body { margin-top: 9px; font-size: 14px; line-height: 1.8; color: #57534E; }
.cert-body strong { color: #1F2937; }
.cert-foot { margin-top: 9px; font-size: 12px; color: #A8A29E; }
/* 印章感圆标 */
.cert-seal {
  position: absolute; right: 12px; bottom: 10px;
  width: 46px; height: 46px; border-radius: 50%;
  border: 2px solid rgba(220, 38, 38, 0.75);
  color: rgba(220, 38, 38, 0.85);
  font-size: 11px; font-weight: 700; letter-spacing: 1px;
  display: flex; align-items: center; justify-content: center; text-align: center;
  transform: rotate(-12deg);
  background: rgba(255, 255, 255, 0.35);
}

/* ================= 成长记录表（课表式网格） ================= */
.record-wrap { overflow-x: auto; }
.record-table {
  width: 100%; min-width: 640px; border-collapse: collapse; font-size: 14px;
  border: 2px solid #D6DCE6;
}
.record-table th, .record-table td {
  padding: 10px 12px; text-align: left; vertical-align: middle;
  border: 1px solid #E3E8F0;
}
.record-table th {
  background: var(--primary-50); color: var(--primary-dark);
  font-size: 13px; font-weight: 700; white-space: nowrap;
  border-bottom: 2px solid #C9D6F2;
}
.record-table tbody tr:nth-child(even) td { background: #FAFBFC; }
.record-time { white-space: nowrap; color: var(--text-2); font-size: 13px; }
.record-step { font-weight: 600; }
</style>
