<template>
  <figure class="question-figure">
    <svg
      viewBox="0 0 640 400"
      role="img"
      aria-label="题目示意图"
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        <clipPath :id="clipId">
          <rect :x="plot.left" :y="plot.top" :width="plot.width" :height="plot.height" />
        </clipPath>
      </defs>
      <g v-if="figure.grid && figure.axes" class="figure-grid">
        <line v-for="tick in xTicks" :key="`gx${tick}`" :x1="x(tick)" :y1="plot.top" :x2="x(tick)" :y2="plot.bottom" />
        <line v-for="tick in yTicks" :key="`gy${tick}`" :x1="plot.left" :y1="y(tick)" :x2="plot.right" :y2="y(tick)" />
      </g>
      <g v-if="figure.axes" class="figure-axes">
        <line v-if="insideY(0)" :x1="plot.left" :y1="y(0)" :x2="plot.right" :y2="y(0)" />
        <line v-if="insideX(0)" :x1="x(0)" :y1="plot.top" :x2="x(0)" :y2="plot.bottom" />
        <text v-if="insideY(0)" :x="plot.right - 3" :y="y(0) - 8" text-anchor="end">{{ figure.x_label || 'x' }}</text>
        <text v-if="insideX(0)" :x="x(0) + 8" :y="plot.top + 11">{{ figure.y_label || 'y' }}</text>
        <text v-if="insideY(0)" v-for="tick in xTicks.filter(v => v !== 0)" :key="`xt${tick}`" :x="x(tick)" :y="y(0) + 15" text-anchor="middle">{{ tickLabel(tick) }}</text>
        <text v-if="insideX(0)" v-for="tick in yTicks.filter(v => v !== 0)" :key="`yt${tick}`" :x="x(0) - 7" :y="y(tick) + 4" text-anchor="end">{{ tickLabel(tick) }}</text>
      </g>
      <g :clip-path="`url(#${clipId})`">
        <g v-for="(element, index) in figure.elements" :key="index" class="figure-elements" :class="`figure-${element.color || 'blue'}`">
          <template v-if="element.type === 'point'">
            <circle class="figure-point" :cx="x(element.x)" :cy="y(element.y)" r="4.5" />
            <text v-if="element.label" class="figure-label" :x="x(element.x) + 8" :y="y(element.y) - 8">{{ element.label }}</text>
          </template>
          <template v-else-if="element.type === 'segment' || element.type === 'line'">
            <line v-if="lineEnds(element)" class="figure-stroke" :x1="x(lineEnds(element)![0].x)" :y1="y(lineEnds(element)![0].y)" :x2="x(lineEnds(element)![1].x)" :y2="y(lineEnds(element)![1].y)" />
            <text v-if="element.label" class="figure-label" :x="x((element.start.x + element.end.x) / 2) + 5" :y="y((element.start.y + element.end.y) / 2) - 7">{{ element.label }}</text>
          </template>
          <template v-else-if="element.type === 'circle'">
            <circle class="figure-stroke" :cx="x(element.cx)" :cy="y(element.cy)" :r="element.radius * plot.scale" />
            <text v-if="element.label" class="figure-label" :x="x(element.cx) + element.radius * plot.scale + 5" :y="y(element.cy)">{{ element.label }}</text>
          </template>
          <template v-else-if="element.type === 'polyline' || element.type === 'polygon'">
            <polygon v-if="element.type === 'polygon'" class="figure-stroke figure-polygon" :points="points(element.points)" />
            <polyline v-else class="figure-stroke" :points="points(element.points)" />
            <text v-if="element.label && element.points[0]" class="figure-label" :x="x(element.points[0].x) + 6" :y="y(element.points[0].y) - 7">{{ element.label }}</text>
          </template>
          <template v-else-if="element.type === 'quadratic'">
            <path class="figure-stroke" :d="quadraticPath(element)" />
            <text v-if="element.label" class="figure-label" :x="x(quadraticLabelPoint(element).x) + 6" :y="y(quadraticLabelPoint(element).y) - 7">{{ element.label }}</text>
          </template>
          <text v-else-if="element.type === 'text'" class="figure-label" :x="x(element.x)" :y="y(element.y)">{{ element.text }}</text>
        </g>
      </g>
    </svg>
  </figure>
</template>

<script setup lang="ts">
import { computed, useId } from 'vue'
import type { FigureElement, FigurePoint, FigureSpec } from '../api/types'

const props = defineProps<{ figure: FigureSpec }>()
const W = 640
const H = 400
const PAD = 32
const clipId = `figure-clip-${useId().replace(/:/g, '')}`
const plot = computed(() => {
  const b = props.figure.bounds
  const xSpan = Math.max(0.1, b.x_max - b.x_min)
  const ySpan = Math.max(0.1, b.y_max - b.y_min)
  const scale = Math.min((W - PAD * 2) / xSpan, (H - PAD * 2) / ySpan)
  const width = xSpan * scale
  const height = ySpan * scale
  const left = (W - width) / 2
  const top = (H - height) / 2
  return { scale, left, top, width, height, right: left + width, bottom: top + height }
})

function x(value: number) { return plot.value.left + (value - props.figure.bounds.x_min) * plot.value.scale }
function y(value: number) { return plot.value.bottom - (value - props.figure.bounds.y_min) * plot.value.scale }
function insideX(value: number) { return value >= props.figure.bounds.x_min && value <= props.figure.bounds.x_max }
function insideY(value: number) { return value >= props.figure.bounds.y_min && value <= props.figure.bounds.y_max }
function tickLabel(value: number) { return Number.isInteger(value) ? String(value) : String(Number(value.toPrecision(3))) }
function niceStep(span: number) {
  const raw = span / 10
  const power = 10 ** Math.floor(Math.log10(raw))
  const normalized = raw / power
  return (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * power
}
function makeTicks(min: number, max: number) {
  const step = niceStep(max - min)
  const first = Math.ceil(min / step) * step
  const count = Math.min(30, Math.floor((max - first) / step) + 1)
  return Array.from({ length: Math.max(0, count) }, (_, i) => Number((first + i * step).toPrecision(6)))
}
const xTicks = computed(() => makeTicks(props.figure.bounds.x_min, props.figure.bounds.x_max))
const yTicks = computed(() => makeTicks(props.figure.bounds.y_min, props.figure.bounds.y_max))
function points(items: FigurePoint[]) { return items.map(p => `${x(p.x)},${y(p.y)}`).join(' ') }

function lineEnds(element: Extract<FigureElement, { type: 'segment' | 'line' }>): [FigurePoint, FigurePoint] | null {
  if (element.type === 'segment') return [element.start, element.end]
  const { x_min, x_max, y_min, y_max } = props.figure.bounds
  const { start, end } = element
  const dx = end.x - start.x
  const dy = end.y - start.y
  if (Math.abs(dx) + Math.abs(dy) < 1e-8) return null
  const candidates: FigurePoint[] = []
  const add = (p: FigurePoint) => {
    if (p.x >= x_min - 1e-7 && p.x <= x_max + 1e-7 && p.y >= y_min - 1e-7 && p.y <= y_max + 1e-7
      && !candidates.some(q => Math.hypot(q.x - p.x, q.y - p.y) < 1e-6)) candidates.push(p)
  }
  if (Math.abs(dx) > 1e-8) {
    for (const vx of [x_min, x_max]) add({ x: vx, y: start.y + (vx - start.x) * dy / dx })
  }
  if (Math.abs(dy) > 1e-8) {
    for (const vy of [y_min, y_max]) add({ x: start.x + (vy - start.y) * dx / dy, y: vy })
  }
  if (candidates.length < 2) return [start, end]
  let pair: [FigurePoint, FigurePoint] = [candidates[0], candidates[1]]
  let farthest = 0
  for (let i = 0; i < candidates.length; i++) for (let j = i + 1; j < candidates.length; j++) {
    const distance = Math.hypot(candidates[i].x - candidates[j].x, candidates[i].y - candidates[j].y)
    if (distance > farthest) { farthest = distance; pair = [candidates[i], candidates[j]] }
  }
  return pair
}

function quadraticY(element: Extract<FigureElement, { type: 'quadratic' }>, xv: number) {
  return element.a * xv * xv + element.b * xv + element.c
}
function quadraticPath(element: Extract<FigureElement, { type: 'quadratic' }>) {
  const min = Math.max(props.figure.bounds.x_min, element.x_min ?? props.figure.bounds.x_min)
  const max = Math.min(props.figure.bounds.x_max, element.x_max ?? props.figure.bounds.x_max)
  const samples = 120
  return Array.from({ length: samples + 1 }, (_, i) => {
    const xv = min + (max - min) * i / samples
    return `${i === 0 ? 'M' : 'L'}${x(xv).toFixed(2)},${y(quadraticY(element, xv)).toFixed(2)}`
  }).join(' ')
}
function quadraticLabelPoint(element: Extract<FigureElement, { type: 'quadratic' }>): FigurePoint {
  const xv = (element.x_min ?? props.figure.bounds.x_min) + ((element.x_max ?? props.figure.bounds.x_max) - (element.x_min ?? props.figure.bounds.x_min)) * 0.72
  return { x: xv, y: quadraticY(element, xv) }
}
</script>

<style scoped>
.question-figure { width: min(100%, 640px); margin: 12px auto 4px; color: var(--text-2); }
.question-figure svg { display: block; width: 100%; height: auto; overflow: visible; }
.figure-grid line { stroke: #E5E7EB; stroke-width: 1; }
.figure-axes line { stroke: #6B7280; stroke-width: 1.35; }
.figure-axes text { fill: #6B7280; font-size: 12px; font-family: inherit; }
.figure-stroke { fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.figure-polygon { fill: color-mix(in srgb, currentColor 8%, transparent); }
.figure-point { fill: currentColor; }
.figure-label { fill: currentColor; font-size: 13px; font-family: inherit; }
.figure-blue { color: var(--primary); }
.figure-red { color: var(--red); }
.figure-green { color: var(--green); }
.figure-amber { color: var(--amber); }
.figure-gray { color: var(--text-2); }
</style>
