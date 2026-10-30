<template>
  <section class="handwriting-pad" aria-label="电子手写板">
    <canvas
      ref="canvasRef"
      class="handwriting-canvas"
      :class="{ disabled }"
      aria-label="手写答题区域"
      :aria-disabled="disabled"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="finishPointer"
      @pointercancel="finishPointer"
    />
    <div class="handwriting-toolbar" role="toolbar" aria-label="手写工具">
      <button type="button" class="btn small" :class="tool === 'pen' ? '' : 'secondary'" :disabled="disabled" @click="tool = 'pen'">
        <AppIcon name="edit" :size="14" /> 画笔
      </button>
      <button type="button" class="btn small" :class="tool === 'eraser' ? '' : 'secondary'" :disabled="disabled" @click="tool = 'eraser'">
        橡皮擦
      </button>
      <button type="button" class="btn small secondary" :disabled="disabled || !strokes.length" @click="undo">撤销</button>
      <button type="button" class="btn small secondary" :disabled="disabled || !strokes.length" @click="clear">清空</button>
      <span class="handwriting-spacer" />
      <button type="button" class="btn small" :disabled="disabled || !strokes.length" @click="submit">
        {{ disabled ? '处理中…' : '提交手写' }}
      </button>
    </div>
    <p v-if="error" class="handwriting-error" role="alert">{{ error }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AppIcon from './icons/AppIcon.vue'

type Point = { x: number; y: number; pressure: number }
type Tool = 'pen' | 'eraser'
type Stroke = { tool: Tool; points: Point[] }

const props = withDefaults(defineProps<{ storageKey: string; disabled?: boolean }>(), {
  disabled: false
})
const emit = defineEmits<{ (event: 'submit', file: File): void }>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const strokes = ref<Stroke[]>([])
const tool = ref<Tool>('pen')
const error = ref('')
const hasInk = computed(() => strokes.value.some((stroke) => stroke.tool === 'pen'))
let activeStroke: Stroke | null = null
let activePointerId: number | null = null
let resizeObserver: ResizeObserver | null = null

function loadDraft() {
  try {
    const raw = localStorage.getItem(props.storageKey)
    if (!raw) return
    const saved: unknown = JSON.parse(raw)
    if (!Array.isArray(saved)) return
    strokes.value = saved.flatMap((item): Stroke[] => {
      if (!item || typeof item !== 'object' || !Array.isArray((item as Stroke).points)) return []
      const candidate = item as Stroke
      if (candidate.tool !== 'pen' && candidate.tool !== 'eraser') return []
      const points = candidate.points.filter((point): point is Point =>
        !!point && Number.isFinite(point.x) && Number.isFinite(point.y) &&
        Number.isFinite(point.pressure) && point.x >= 0 && point.x <= 1 &&
        point.y >= 0 && point.y <= 1
      ).slice(0, 4000)
      return points.length ? [{ tool: candidate.tool, points }] : []
    }).slice(0, 300)
  } catch {
    strokes.value = []
  }
}

function saveDraft() {
  try {
    if (strokes.value.length) localStorage.setItem(props.storageKey, JSON.stringify(strokes.value))
    else localStorage.removeItem(props.storageKey)
  } catch {
    error.value = '草稿暂时无法保存在这台设备上。'
  }
}

function pointFromEvent(event: PointerEvent): Point | null {
  const canvas = canvasRef.value
  if (!canvas) return null
  const rect = canvas.getBoundingClientRect()
  if (!rect.width || !rect.height) return null
  return {
    x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
    y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
    pressure: event.pointerType === 'pen' && event.pressure > 0 ? event.pressure : 0.5
  }
}

function drawStrokeSegment(ctx: CanvasRenderingContext2D, stroke: Stroke, from: Point, to: Point) {
  const canvas = canvasRef.value
  if (!canvas) return
  const width = canvas.clientWidth
  const height = canvas.clientHeight
  ctx.beginPath()
  ctx.moveTo(from.x * width, from.y * height)
  ctx.lineTo(to.x * width, to.y * height)
  ctx.strokeStyle = stroke.tool === 'eraser' ? '#FFFFFF' : '#1F2937'
  ctx.lineWidth = stroke.tool === 'eraser' ? 22 : 1.6 + to.pressure * 2.4
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.stroke()
}

function drawDot(ctx: CanvasRenderingContext2D, stroke: Stroke, point: Point) {
  const canvas = canvasRef.value
  if (!canvas) return
  const radius = (stroke.tool === 'eraser' ? 22 : 1.6 + point.pressure * 2.4) / 2
  ctx.beginPath()
  ctx.arc(point.x * canvas.clientWidth, point.y * canvas.clientHeight, radius, 0, Math.PI * 2)
  ctx.fillStyle = stroke.tool === 'eraser' ? '#FFFFFF' : '#1F2937'
  ctx.fill()
}

function redraw() {
  const canvas = canvasRef.value
  const ctx = canvas?.getContext('2d')
  if (!canvas || !ctx) return
  ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight)
  ctx.fillStyle = '#FFFFFF'
  ctx.fillRect(0, 0, canvas.clientWidth, canvas.clientHeight)
  for (const stroke of strokes.value) {
    if (!stroke.points.length) continue
    if (stroke.points.length === 1) {
      drawDot(ctx, stroke, stroke.points[0])
      continue
    }
    for (let index = 1; index < stroke.points.length; index++) {
      drawStrokeSegment(ctx, stroke, stroke.points[index - 1], stroke.points[index])
    }
  }
}

function resizeCanvas() {
  const canvas = canvasRef.value
  if (!canvas) return
  const rect = canvas.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  const ratio = Math.min(window.devicePixelRatio || 1, 3)
  const width = Math.round(rect.width * ratio)
  const height = Math.round(rect.height * ratio)
  if (canvas.width === width && canvas.height === height) return
  canvas.width = width
  canvas.height = height
  canvas.getContext('2d')?.setTransform(ratio, 0, 0, ratio, 0, 0)
  redraw()
}

function onPointerDown(event: PointerEvent) {
  if (props.disabled || activePointerId !== null) return
  event.preventDefault()
  const point = pointFromEvent(event)
  const canvas = canvasRef.value
  const ctx = canvas?.getContext('2d')
  if (!point || !canvas || !ctx) return
  error.value = ''
  activePointerId = event.pointerId
  activeStroke = { tool: tool.value, points: [point] }
  strokes.value.push(activeStroke)
  canvas.setPointerCapture(event.pointerId)
  drawDot(ctx, activeStroke, point)
}

function onPointerMove(event: PointerEvent) {
  if (!activeStroke || event.pointerId !== activePointerId) return
  event.preventDefault()
  const point = pointFromEvent(event)
  const previous = activeStroke.points[activeStroke.points.length - 1]
  const canvas = canvasRef.value
  const ctx = canvas?.getContext('2d')
  if (!point || !previous || !ctx) return
  const dx = (point.x - previous.x) * (canvas?.clientWidth ?? 1)
  const dy = (point.y - previous.y) * (canvas?.clientHeight ?? 1)
  if (Math.hypot(dx, dy) < 0.7) return
  if (activeStroke.points.length < 4000) activeStroke.points.push(point)
  drawStrokeSegment(ctx, activeStroke, previous, point)
}

function finishPointer(event: PointerEvent) {
  if (event.pointerId !== activePointerId || !activeStroke) return
  activeStroke = null
  activePointerId = null
  saveDraft()
}

function undo() {
  if (props.disabled) return
  strokes.value.pop()
  error.value = ''
  saveDraft()
  redraw()
}

function clear() {
  activeStroke = null
  activePointerId = null
  strokes.value = []
  error.value = ''
  try { localStorage.removeItem(props.storageKey) } catch { /* storage is optional */ }
  redraw()
}

function submit() {
  if (props.disabled || !hasInk.value) return
  const canvas = canvasRef.value
  if (!canvas) return
  error.value = ''
  canvas.toBlob((blob) => {
    if (!blob) {
      error.value = '手写内容生成失败，请重试。'
      return
    }
    emit('submit', new File([blob], `handwriting-${Date.now()}.png`, { type: 'image/png' }))
  }, 'image/png')
}

onMounted(() => {
  loadDraft()
  resizeCanvas()
  if (canvasRef.value) {
    resizeObserver = new ResizeObserver(resizeCanvas)
    resizeObserver.observe(canvasRef.value)
  }
  redraw()
})

onBeforeUnmount(() => resizeObserver?.disconnect())

defineExpose({ clear })
</script>

<style scoped>
.handwriting-pad { margin-top: 10px; }
.handwriting-canvas {
  display: block;
  width: 100%;
  height: 280px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: #fff;
  touch-action: none;
  cursor: crosshair;
}
.handwriting-canvas.disabled { cursor: wait; opacity: 0.72; }
.handwriting-toolbar { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; margin-top: 8px; }
.handwriting-spacer { flex: 1 1 auto; }
.handwriting-error { color: var(--red); font-size: 13px; margin-top: 7px; }
@media (max-width: 640px) {
  .handwriting-canvas { height: 240px; }
  .handwriting-toolbar { gap: 6px; }
  .handwriting-spacer { display: none; }
}
</style>
