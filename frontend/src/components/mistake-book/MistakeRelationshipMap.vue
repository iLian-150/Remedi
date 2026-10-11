<template>
  <section v-if="mode === 'mindmap'" class="mistake-map-section" :class="{ 'is-split': split, 'is-reversed': reversed, 'is-assistant-fullscreen': fullscreen }" aria-label="错题思维导图">
    <template v-if="subjects.length">
      <div class="mistake-map-guide"><div class="mistake-map-tools" role="group" aria-label="导图操作">
        <button type="button" :disabled="zoom <= 0.65" aria-label="缩小导图" @click="zoomBy(-0.1)"><AppIcon name="minus" :size="14"/></button><span>{{ Math.round(zoom * 100) }}%</span><button type="button" :disabled="zoom >= 1.4" aria-label="放大导图" @click="zoomBy(0.1)"><AppIcon name="plus" :size="14"/></button><button type="button" class="mistake-map-home" @click="resetMap">回到中心</button>
      </div></div>
      <div class="mistake-map-branch-nav" role="group" aria-label="选择学科">
        <button v-for="branch in branches" :key="branch.key" type="button" :class="{ selected: branch.key === selectedSubjectKey }" :aria-pressed="branch.key === selectedSubjectKey" @click="selectSubject(branch.key)"><span class="mistake-map-branch-swatch" :style="{ backgroundColor: branch.color }"/><span>{{ branch.label }}</span><small>{{ branch.recordCount }}</small></button>
      </div>
      <div class="mistake-map-viewport-frame">
        <div ref="viewport" class="mistake-map-viewport" :class="{ 'is-panning': isPanning }" role="region" aria-label="思维导图画布" @pointerdown="startPanning" @pointermove="movePanning" @pointerup="stopPanning" @pointercancel="stopPanning" @lostpointercapture="stopPanning">
          <div class="mistake-map-stage" :style="{ width: `${1680 * zoom}px`, height: `${canvasHeight * zoom}px` }">
            <div class="mistake-map-scaled" :style="{ width: `${1680 * zoom}px`, height: `${canvasHeight * zoom}px` }">
              <div class="mistake-map-canvas" :style="{ width: '1680px', height: `${canvasHeight}px`, transform: `scale(${zoom})`, transformOrigin: 'top left' }">
                <svg class="mistake-map-lines" width="1680" :height="canvasHeight" :viewBox="`0 0 1680 ${canvasHeight}`" aria-hidden="true">
                  <path v-for="branch in branches" :key="`root-${branch.key}`" :d="curve({ x: root.x + (branch.side === 'left' ? -80 : 80), y: root.y }, { x: branch.x + (branch.side === 'left' ? 65 : -65), y: branch.y }, branch.side)" :stroke="branch.color"/>
                  <template v-if="activeBranch">
                    <path v-for="(topic, index) in activeSubject?.topics" :key="`topic-${topic.key}`" class="topic-line" :d="curve({ x: activeBranch.x + (activeBranch.side === 'left' ? -65 : 65), y: activeBranch.y }, { x: topicPoints[index].x + (activeBranch.side === 'left' ? 74 : -74), y: topicPoints[index].y }, activeBranch.side)" :stroke="activeBranch.color"/>
                  </template>
                  <template v-if="activeBranch && activeTopicPoint">
                    <path v-for="(point, index) in activeTopic?.errorPoints" :key="`leaf-${point.key}`" class="leaf-line" :d="curve({ x: activeTopicPoint.x + (activeBranch.side === 'left' ? -74 : 74), y: activeTopicPoint.y }, { x: leafPoints[index].x + (activeBranch.side === 'left' ? 74 : -74), y: leafPoints[index].y }, activeBranch.side)" :stroke="activeBranch.color"/>
                  </template>
                </svg>
                <button ref="mapRoot" class="mistake-map-root" type="button" :style="pointStyle(root)" aria-label="回到思维导图中心" @click="resetMap"><span>学习脉络</span><strong>我的错题</strong><small>{{ studentName || '学习档案' }} · {{ recordCount }} 条记录</small></button>
                <button v-for="branch in branches" :key="branch.key" class="mistake-map-branch" :class="{ selected: branch.key === selectedSubjectKey }" type="button" :style="{ ...pointStyle(branch), '--accent': branch.color }" :aria-pressed="branch.key === selectedSubjectKey" @click="selectSubject(branch.key)"><span>{{ branch.label }}</span><small>{{ branch.topics.length }} 个知识点 · {{ branch.recordCount }} 条错题</small></button>
                <template v-if="activeSubject">
                  <button v-for="(topic, index) in activeSubject.topics" :key="topic.key" class="mistake-map-topic-node" :class="{ selected: topic.key === selectedTopicKey }" type="button" :style="{ ...pointStyle(topicPoints[index]), '--accent': activeBranch?.color }" :aria-pressed="topic.key === selectedTopicKey" @click="selectTopic(topic.key)"><strong>{{ topic.label }}</strong><small>{{ topic.entries.length }} 条错题 · {{ topic.errorPoints.length }} 个错误点{{ topic.studied ? ' · 已学完' : '' }}</small></button>
                </template>
                <template v-if="activeTopic">
                  <button v-for="(point, index) in activeTopic.errorPoints" :key="point.key" class="mistake-map-leaf-node" :class="{ studied: point.studied, selected: point.key === selectedPointKey }" type="button" :style="{ ...pointStyle(leafPoints[index]), '--accent': activeBranch?.color }" @click="openPoint(point)" :aria-label="`打开错误点问答：${point.label}`"><strong>{{ point.label }}</strong><small>{{ point.entries.length }} 道相关错题 · <span v-if="point.studied">已学会</span><span v-else>查看问答 <AppIcon name="arrow-up-right" :size="11"/></span></small></button>
                </template>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
    <div v-else class="mistake-board-empty"><strong>错题本还很空</strong><span>完成作业诊断后，错题会出现在这里。</span></div>
    <slot name="assistant" />
  </section>

  <section v-else class="mistake-network" :class="{ 'is-split': split, 'is-reversed': reversed, 'is-assistant-fullscreen': fullscreen }" aria-label="错题知识点关联图谱">
    <template v-if="subjects.length">
      <div class="mistake-network-heading"><div class="mistake-network-heading-actions"><div class="mistake-network-controls" role="group" aria-label="图谱缩放与定位"><button type="button" :disabled="zoom <= 0.6" aria-label="缩小图谱" @click="zoomBy(-0.15)"><AppIcon name="minus" :size="14"/></button><span>{{ Math.round(zoom * 100) }}%</span><button type="button" :disabled="zoom >= 1.4" aria-label="放大图谱" @click="zoomBy(0.15)"><AppIcon name="plus" :size="14"/></button><button class="mistake-network-center-button" type="button" @click="resetMap">回到中心</button></div></div></div>
      <div v-if="activeSubject" class="mistake-network-topic-nav" role="group" aria-label="快速切换学科和知识点">
        <select aria-label="选择学科" :value="activeSubject.key" @change="selectSubject(($event.target as HTMLSelectElement).value)"><option v-for="subject in subjects" :key="subject.key" :value="subject.key">{{ subject.label }}</option></select>
        <button v-for="topic in activeSubject.topics" :key="topic.key" type="button" :class="{ selected: topic.key === selectedTopicKey }" @click="selectTopic(topic.key)">{{ topic.label }} · {{ topic.entries.length }}</button>
      </div>
      <div class="mistake-network-frame">
        <div ref="viewport" class="mistake-network-viewport" :class="{ 'is-panning': isPanning }" role="region" aria-label="错题关联图画布" @pointerdown="startPanning" @pointermove="movePanning" @pointerup="stopPanning" @pointercancel="stopPanning" @lostpointercapture="stopPanning">
          <div class="mistake-network-stage" :style="{ width: `${networkWidth * zoom}px`, height: `${networkHeight * zoom}px` }">
            <div class="mistake-network-scaled" :style="{ width: `${networkWidth * zoom}px`, height: `${networkHeight * zoom}px` }">
              <div class="mistake-network-canvas" :style="{ width: `${networkWidth}px`, height: `${networkHeight}px`, transform: `scale(${zoom})`, transformOrigin: 'top left' }">
                <svg class="mistake-network-lines" :width="networkWidth" :height="networkHeight" :viewBox="`0 0 ${networkWidth} ${networkHeight}`" aria-hidden="true">
                  <defs><filter id="mistake-network-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
                  <g class="mistake-network-orbits"><ellipse v-for="(ring, index) in orbitRings" :key="`ring-${index}`" :cx="hub.x" :cy="hub.y" :rx="ring.rx" :ry="ring.ry"/><line v-for="angle in 24" :key="`ray-${angle}`" :x1="hub.x" :y1="hub.y" :x2="ringPoint(hub, radii.errorX, radii.errorY, (angle - 1) * Math.PI / 12).x" :y2="ringPoint(hub, radii.errorX, radii.errorY, (angle - 1) * Math.PI / 12).y"/></g>
                  <circle class="mistake-network-core-glow" :cx="hub.x" :cy="hub.y" r="92"/>
                  <g v-for="(subject, index) in subjects" :key="`subject-link-${subject.key}`"><path class="mistake-network-beam subject-beam" :d="signalPath(hub, subjectPoints[index], index % 2 ? -1 : 1)" :stroke="subjectColor(index)"/><path class="mistake-network-tracer" :d="signalPath(hub, subjectPoints[index], index % 2 ? -1 : 1)"/><circle class="mistake-network-anchor" :cx="subjectPoints[index].x" :cy="subjectPoints[index].y" r="15" :stroke="subjectColor(index)"/></g>
                  <g v-if="subjectExpanded && activeSubject"><template v-for="(topic, index) in activeSubject.topics" :key="`topic-line-${topic.key}`"><path class="mistake-network-beam topic-beam" :class="{ active: topic.key === selectedTopicKey }" :d="signalPath(hub, networkTopicPoints[index], index % 2 ? -.85 : .85)" :stroke="activeColor"/><path class="mistake-network-hierarchy" :d="signalPath(activeSubjectPoint, networkTopicPoints[index], index % 2 ? -.4 : .4)"/><circle class="mistake-network-anchor topic-anchor" :cx="networkTopicPoints[index].x" :cy="networkTopicPoints[index].y" r="13" :stroke="activeColor"/></template></g>
                  <g v-if="activeTopic"><template v-for="(point, index) in activeTopic.errorPoints" :key="`point-line-${point.key}`"><path class="mistake-network-beam leaf-beam" :d="signalPath(hub, pointPoints[index], index % 2 ? -.75 : .75)" :stroke="activeColor"/><path class="mistake-network-hierarchy leaf-hierarchy" :d="signalPath(networkActiveTopicPoint || hub, pointPoints[index], index % 2 ? -.4 : .4)"/><circle class="mistake-network-anchor leaf-anchor" :cx="pointPoints[index].x" :cy="pointPoints[index].y" r="15" :stroke="activeColor"/></template></g>
                </svg>
                <button v-for="(subject, index) in subjects" :key="subject.key" class="mistake-network-node subject-node" :class="{ selected: subjectExpanded && subject.key === activeSubject?.key }" type="button" :style="{ ...pointStyle(subjectPoints[index]), '--accent': subjectColor(index) }" @click="selectSubject(subject.key)"><span class="mistake-network-node-mark" aria-hidden="true"/><strong>{{ subject.label }}</strong><small>{{ subject.topics.length }} 个知识点 · {{ subject.recordCount }} 条错题</small></button>
                <template v-if="subjectExpanded && activeSubject"><button v-for="(topic, index) in activeSubject.topics" :key="topic.key" class="mistake-network-node topic-node knowledge-node" :class="{ selected: topic.key === selectedTopicKey }" type="button" :style="{ ...pointStyle(networkTopicPoints[index]), '--accent': activeColor }" @click="selectTopic(topic.key)"><span class="mistake-network-node-mark" aria-hidden="true"/><strong>{{ topic.label }}</strong><small>{{ topic.entries.length }} 条错题 · {{ topic.errorPoints.length }} 个错误点{{ topic.studied ? ' · 已学完' : '' }}</small></button></template>
                <template v-if="activeTopic"><button v-for="(point, index) in activeTopic.errorPoints" :key="point.key" class="mistake-network-node leaf-node" :class="{ studied: point.studied, selected: point.key === selectedPointKey }" type="button" :style="{ ...pointStyle(pointPoints[index]), '--accent': activeColor }" @click="openPoint(point)"><strong>{{ point.label }}</strong><small>{{ point.entries.length }} 道相关错题 · <span v-if="point.studied">已学会</span><span v-else>查看问答 <AppIcon name="arrow-up-right" :size="11"/></span></small></button></template>
                <div ref="networkHub" class="mistake-network-hub" :style="pointStyle(hub)"><span>知</span><strong>{{ studentName || '我的' }}</strong><small>{{ recordCount }} 条错题</small></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
    <div v-else class="mistake-board-empty"><strong>错题本还很空</strong><span>完成作业诊断后，错题会出现在这里。</span></div>
    <slot name="assistant" />
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { StudentMistake } from '../../api/types'
import AppIcon from '../icons/AppIcon.vue'

type Point = { x: number; y: number }
type ErrorPoint = { key: string; label: string; entries: StudentMistake[]; studied: boolean }
type Topic = { key: string; label: string; entries: StudentMistake[]; errorPoints: ErrorPoint[]; studied: boolean }
type SubjectGroup = { key: string; label: string; topics: Topic[]; recordCount: number }

const props = defineProps<{ mode: 'mindmap' | 'network'; mistakes: StudentMistake[]; studentName?: string; split?: boolean; reversed?: boolean; fullscreen?: boolean }>()
const emit = defineEmits<{ select: [mistake: StudentMistake] }>()
const zoom = ref(props.mode === 'network' ? 0.85 : 1)
const selectedSubjectKey = ref<string | null>(null)
const selectedTopicKey = ref<string | null>(null)
const selectedPointKey = ref<string | null>(null)
const viewport = ref<HTMLElement | null>(null)
const mapRoot = ref<HTMLElement | null>(null)
const networkHub = ref<HTMLElement | null>(null)
const isPanning = ref(false)
let panStart: { pointerId: number; x: number; y: number; scrollLeft: number; scrollTop: number } | null = null

const subjectNames: Record<string, string> = { math: '数学', english: '英语', english_exercise: '英语练习', physics: '物理', chemistry: '化学', biology: '生物', chinese: '语文', history: '历史', geography: '地理', politics: '道德与法治', computer_science: '信息科技' }
const colors = ['#1D4ED8', '#059669', '#D97706', '#DC2626', '#7C3AED', '#0284C7', '#DB2777', '#65A30D']
const subjects = computed<SubjectGroup[]>(() => {
  const result = new Map<string, SubjectGroup>()
  for (const entry of props.mistakes) {
    const subjectKey = entry.question_subject || 'other'
    const subject = result.get(subjectKey) ?? { key: subjectKey, label: subjectNames[subjectKey] || subjectKey, topics: [], recordCount: 0 }
    let topic = subject.topics.find((item) => item.label === (entry.knowledge_point || '待归类'))
    if (!topic) {
      topic = { key: `${subjectKey}:${entry.knowledge_point || '待归类'}`, label: entry.knowledge_point || '待归类', entries: [], errorPoints: [], studied: true }
      subject.topics.push(topic)
    }
    topic.entries.push(entry)
    topic.studied = topic.studied && entry.category_studied
    let point = topic.errorPoints.find((item) => item.key === entry.category_key)
    if (!point) {
      point = { key: entry.category_key, label: entry.category_label || entry.error_type, entries: [], studied: true }
      topic.errorPoints.push(point)
    }
    point.entries.push(entry)
    point.studied = point.studied && entry.category_studied
    subject.recordCount += 1
    result.set(subjectKey, subject)
  }
  for (const subject of result.values()) {
    subject.topics.sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
    for (const topic of subject.topics) topic.errorPoints.sort((a, b) => Number(a.studied) - Number(b.studied) || b.entries.length - a.entries.length)
  }
  return Array.from(result.values())
})
const activeSubject = computed(() => subjects.value.find((item) => item.key === selectedSubjectKey.value))
const activeBranch = computed(() => branches.value.find((item) => item.key === activeSubject.value?.key))
const activeTopic = computed(() => activeSubject.value?.topics.find((item) => item.key === selectedTopicKey.value))
const activeTopicPoint = computed<Point | undefined>(() => topicPoints.value[activeSubject.value?.topics.findIndex((item) => item.key === activeTopic.value?.key) ?? -1])
const recordCount = computed(() => subjects.value.reduce((total, item) => total + item.recordCount, 0))
const canvasHeight = computed(() => Math.max(620, (Math.ceil(subjects.value.length / 2) - 1) * 114 + 620, (activeSubject.value?.topics.length || 0) * 68 + 220, (activeTopic.value?.errorPoints.length || 0) * 58 + 220))
const root = computed<Point>(() => ({ x: 840, y: canvasHeight.value / 2 }))
const branches = computed(() => subjects.value.map((subject, index) => {
  const side: 'left' | 'right' = index % 2 === 0 ? 'left' : 'right'
  const count = side === 'left' ? Math.ceil(subjects.value.length / 2) : Math.floor(subjects.value.length / 2)
  return { ...subject, side, x: side === 'left' ? 655 : 1025, y: root.value.y + (Math.floor(index / 2) - (count - 1) / 2) * 114, color: colors[index % colors.length] }
}))
const topicPoints = computed<Point[]>(() => activeSubject.value?.topics.map((_, index) => ({ x: (activeBranch.value?.x || 840) + (activeBranch.value?.side === 'left' ? -175 : 175), y: root.value.y + (index - ((activeSubject.value?.topics.length || 1) - 1) / 2) * 68 })) || [])
const leafPoints = computed<Point[]>(() => activeTopic.value?.errorPoints.map((_, index) => ({ x: (topicPoints.value[activeSubject.value?.topics.findIndex((item) => item.key === activeTopic.value?.key) ?? 0]?.x || 840) + (activeBranch.value?.side === 'left' ? -170 : 170), y: root.value.y + (index - ((activeTopic.value?.errorPoints.length || 1) - 1) / 2) * 58 })) || [])

const networkWidth = computed(() => 2400 + Math.max(0, Math.ceil((activeSubject.value?.topics.length || 0) / 8) - 1) * 360)
const networkHeight = computed(() => 1650 + Math.max(0, Math.ceil((activeSubject.value?.topics.length || 0) / 8) - 1) * 260)
const hub = computed<Point>(() => ({ x: networkWidth.value / 2, y: networkHeight.value / 2 }))
const activeSubjectIndex = computed(() => subjects.value.findIndex((item) => item.key === activeSubject.value?.key))
const subjectExpanded = computed(() => Boolean(selectedSubjectKey.value && selectedSubjectKey.value === activeSubject.value?.key))
const radii = computed(() => ({ subjectX: subjects.value.length > 8 ? 400 : 300, subjectY: subjects.value.length > 8 ? 320 : 220, topicX: (subjects.value.length > 8 ? 400 : 300) + 190, topicY: (subjects.value.length > 8 ? 320 : 220) + 125, errorX: (subjects.value.length > 8 ? 400 : 300) + 390, errorY: (subjects.value.length > 8 ? 320 : 220) + 280 }))
const subjectPoints = computed(() => subjects.value.map((_, index) => ringPoint(hub.value, radii.value.subjectX, radii.value.subjectY, subjectAngle(index, subjects.value.length))))
const activeSubjectPoint = computed(() => subjectPoints.value[activeSubjectIndex.value])
const activeColor = computed(() => colors[Math.max(0, activeSubjectIndex.value) % colors.length])
const networkTopicPoints = computed(() => activeSubject.value?.topics.map((_, index) => {
  const count = activeSubject.value?.topics.length || 1
  const angle = subjectAngle(Math.max(0, activeSubjectIndex.value), subjects.value.length) + (count === 1 ? 0 : -0.65 + index * 1.3 / (count - 1))
  return ringPoint(hub.value, radii.value.topicX, radii.value.topicY, angle)
}) || [])
const activeTopicIndex = computed(() => activeSubject.value?.topics.findIndex((item) => item.key === activeTopic.value?.key) ?? -1)
const networkActiveTopicPoint = computed(() => networkTopicPoints.value[activeTopicIndex.value])
const pointPoints = computed(() => activeTopic.value?.errorPoints.map((_, index) => {
  const count = activeTopic.value?.errorPoints.length || 1
  const direction = networkActiveTopicPoint.value ? Math.atan2((networkActiveTopicPoint.value.y - hub.value.y) / radii.value.topicY, (networkActiveTopicPoint.value.x - hub.value.x) / radii.value.topicX) : subjectAngle(Math.max(0, activeSubjectIndex.value), subjects.value.length)
  const angle = direction + (count === 1 ? 0 : -0.8 + index * 1.6 / (count - 1))
  return ringPoint(hub.value, radii.value.errorX, radii.value.errorY, angle)
}) || [])
const orbitRings = computed(() => [{ rx: 112, ry: 86 }, { rx: radii.value.subjectX, ry: radii.value.subjectY }, { rx: radii.value.topicX, ry: radii.value.topicY }, { rx: radii.value.errorX, ry: radii.value.errorY }])

watch(() => props.mode, (mode) => { zoom.value = mode === 'network' ? 0.85 : 1; resetMap() })
watch(() => props.mistakes.length, () => { if (selectedSubjectKey.value && !subjects.value.some((item) => item.key === selectedSubjectKey.value)) resetMap() })
watch(() => props.mode === 'network' ? subjects.value[0]?.key ?? '' : '', (firstSubjectKey) => {
  if (firstSubjectKey && !selectedSubjectKey.value) selectedSubjectKey.value = firstSubjectKey
}, { immediate: true })
watch(() => [props.mode, props.split, props.mistakes.length, networkWidth.value, networkHeight.value], () => { void nextTick(() => centerNetwork('auto')) })
watch(() => [zoom.value, selectedPointKey.value], () => { void nextTick(centerNetwork) })
onMounted(() => { void nextTick(() => requestAnimationFrame(() => centerNetwork('auto'))) })

function subjectAngle(index: number, count: number) { if (count === 1) return -Math.PI * 0.36; if (count === 2) return index === 0 ? -Math.PI : 0; return -Math.PI / 2 + index * Math.PI * 2 / count }
function ringPoint(center: Point, radiusX: number, radiusY: number, angle: number): Point { return { x: center.x + Math.cos(angle) * radiusX, y: center.y + Math.sin(angle) * radiusY } }
function signalPath(from: Point, to: Point, direction = 1) {
  const dx = to.x - from.x, dy = to.y - from.y, distance = Math.hypot(dx, dy) || 1
  const sweep = Math.min(115, distance * 0.19) * direction, nx = -dy / distance, ny = dx / distance
  return `M ${from.x} ${from.y} C ${from.x + dx * 0.25 + nx * sweep} ${from.y + dy * 0.25 + ny * sweep}, ${from.x + dx * 0.72 + nx * sweep * 0.72} ${from.y + dy * 0.72 + ny * sweep * 0.72}, ${to.x} ${to.y}`
}
function curve(from: Point, to: Point, side: 'left' | 'right') { const bend = side === 'left' ? -1 : 1; return `M ${from.x} ${from.y} C ${from.x + bend * 26} ${from.y}, ${to.x - bend * 22} ${to.y}, ${to.x} ${to.y}` }
function pointStyle(point: Point) { return { left: `${point.x}px`, top: `${point.y}px` } }
function subjectColor(index: number) { return colors[index % colors.length] }
function startPanning(event: PointerEvent) {
  if (!viewport.value || event.button !== 0 || !event.isPrimary) return
  const target = event.target
  if (target instanceof Element && target.closest('button, a, input, textarea, select')) return
  panStart = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, scrollLeft: viewport.value.scrollLeft, scrollTop: viewport.value.scrollTop }
  isPanning.value = true
  viewport.value.setPointerCapture(event.pointerId)
  event.preventDefault()
}
function movePanning(event: PointerEvent) {
  if (!panStart || panStart.pointerId !== event.pointerId || !viewport.value) return
  viewport.value.scrollLeft = panStart.scrollLeft - (event.clientX - panStart.x)
  viewport.value.scrollTop = panStart.scrollTop - (event.clientY - panStart.y)
}
function stopPanning(event: PointerEvent) {
  if (!panStart || panStart.pointerId !== event.pointerId) return
  const pointerId = panStart.pointerId
  panStart = null
  isPanning.value = false
  if (viewport.value?.hasPointerCapture(pointerId)) viewport.value.releasePointerCapture(pointerId)
}
function zoomBy(amount: number) { zoom.value = Math.min(1.4, Math.max(props.mode === 'mindmap' ? 0.65 : 0.6, Math.round((zoom.value + amount) * 100) / 100)) }
function resetMap() { selectedSubjectKey.value = null; selectedTopicKey.value = null; selectedPointKey.value = null; zoom.value = props.mode === 'network' ? 0.85 : 1; void nextTick(centerNetwork) }
function centerNetwork(behavior: ScrollBehavior = 'smooth') {
  if (!viewport.value) return
  // 按根节点的实际屏幕位置居中，计入画布为拖拽预留的空白区域。
  if (props.mode === 'mindmap') {
    if (!mapRoot.value) return
    const viewportRect = viewport.value.getBoundingClientRect()
    const rootRect = mapRoot.value.getBoundingClientRect()
    const viewportCenterX = viewportRect.left + viewport.value.clientLeft + viewport.value.clientWidth / 2
    const viewportCenterY = viewportRect.top + viewport.value.clientTop + viewport.value.clientHeight / 2
    viewport.value.scrollTo({
      left: viewport.value.scrollLeft + rootRect.left + rootRect.width / 2 - viewportCenterX,
      top: viewport.value.scrollTop + rootRect.top + rootRect.height / 2 - viewportCenterY,
      behavior,
    })
    return
  }
  const selectedNode = selectedPointKey.value
    ? viewport.value.querySelector<HTMLElement>('.mistake-network-node.leaf-node.selected')
    : null
  const target = selectedNode || networkHub.value
  if (!target) return
  const viewportRect = viewport.value.getBoundingClientRect()
  const targetRect = target.getBoundingClientRect()
  const viewportCenterX = viewportRect.left + viewport.value.clientLeft + viewport.value.clientWidth / 2
  const viewportCenterY = viewportRect.top + viewport.value.clientTop + viewport.value.clientHeight / 2
  viewport.value.scrollTo({
    left: viewport.value.scrollLeft + targetRect.left + targetRect.width / 2 - viewportCenterX,
    top: viewport.value.scrollTop + targetRect.top + targetRect.height / 2 - viewportCenterY,
    behavior,
  })
}
function selectSubject(key: string) { selectedSubjectKey.value = key; selectedTopicKey.value = null; selectedPointKey.value = null }
function selectTopic(key: string) { selectedTopicKey.value = key; selectedPointKey.value = null }
function openPoint(point: ErrorPoint) { selectedPointKey.value = point.key; const entry = point.entries.find((item) => !item.category_studied) || point.entries[0]; if (entry) emit('select', entry) }
</script>

<style scoped>
.mistake-map-section, .mistake-network { min-width: 0; min-height: 0; height: 100%; }
.mistake-map-viewport-frame, .mistake-map-viewport, .mistake-network-frame, .mistake-network-viewport { height: 100%; min-height: 0; }
.mistake-network:not(.is-split) .mistake-network-frame, .mistake-network:not(.is-split) .mistake-network-viewport { width: 100%; height: 100%; min-height: 0; }
.mistake-network .mistake-network-viewport { touch-action: none; }
.mistake-network .mistake-network-viewport, .mistake-network .mistake-network-topic-nav { scrollbar-width: none; }
.mistake-network .mistake-network-viewport::-webkit-scrollbar, .mistake-network .mistake-network-topic-nav::-webkit-scrollbar { display: none; width: 0; height: 0; }
.mistake-board-empty { min-height: 100%; height: 100%; }
@media (min-width: 761px) {
  .mistake-network-topic-nav { width: max-content; max-width: calc(100% - 300px); box-sizing: border-box; }
}
</style>
