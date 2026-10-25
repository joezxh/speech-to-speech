<script setup lang="ts">
import { computed } from 'vue'

import { dbToPercent, fractionToDb, GATE_OFF_DB } from '../audio/meter'

const props = defineProps<{ muted: boolean; gateDb: number; levelDb: number }>()
const emit = defineEmits<{
  (e: 'update:muted', value: boolean): void
  (e: 'update:gateDb', value: number): void
}>()

// demo/main.js:493-516：200° 的弧，缺口朝着球体（右侧），0 在左下、1 在左上。
const R = 40
const SPAN = 200
const START = 180 - SPAN / 2

function arcPoint(fraction: number): { x: number; y: number } {
  const rad = ((START + fraction * SPAN) * Math.PI) / 180
  return { x: 50 + R * Math.cos(rad), y: 50 + R * Math.sin(rad) }
}

// 几何只有一条，`d` 不随状态变化，进程内算一次。
const arcPath = ((): string => {
  const a = arcPoint(0)
  const b = arcPoint(1)
  return `M ${a.x} ${a.y} A ${R} ${R} 0 1 1 ${b.x} ${b.y}`
})()

const gateFraction = computed(() => dbToPercent(props.gateDb) / 100)
const levelFraction = computed(() => dbToPercent(props.levelDb) / 100)
const handle = computed(() => arcPoint(gateFraction.value))
const gating = computed(() => props.gateDb > GATE_OFF_DB)
// 电平越过门限 = 门确实开了；门关着的时候弧不该整圈高亮。
const open = computed(() => gating.value && levelFraction.value >= gateFraction.value)

let dragging = false

function dbFromPointer(event: PointerEvent, svg: SVGSVGElement): number {
  const box = svg.getBoundingClientRect()
  let deg = (Math.atan2(event.clientY - (box.top + box.height / 2), event.clientX - (box.left + box.width / 2)) * 180) / Math.PI
  if (deg < 0) deg += 360
  // 落进右侧缺口的角度会算出 [0,1] 之外的值，fractionToDb 会夹到最近的一端。
  return fractionToDb((deg - START) / SPAN)
}

function startDrag(event: PointerEvent): void {
  dragging = true
  const path = event.currentTarget as SVGPathElement
  path.setPointerCapture(event.pointerId)
  const svg = path.ownerSVGElement
  if (svg) emit('update:gateDb', dbFromPointer(event, svg))
}

function moveDrag(event: PointerEvent): void {
  if (!dragging) return
  const svg = (event.currentTarget as SVGPathElement).ownerSVGElement
  if (svg) emit('update:gateDb', dbFromPointer(event, svg))
}

function endDrag(): void {
  dragging = false
}
</script>

<template>
  <div class="mic-gate" :class="{ 'is-gating': gating, 'is-open': open }">
    <svg class="mic-gate__arc" viewBox="0 0 100 100" aria-hidden="true">
      <path class="mic-gate__track" :d="arcPath" fill="none" />
      <path
        class="mic-gate__fill"
        :d="arcPath"
        fill="none"
        pathLength="100"
        :style="{ strokeDashoffset: 100 - levelFraction * 100 }"
      />
      <path
        class="mic-gate__hit"
        :d="arcPath"
        fill="none"
        @pointerdown="startDrag"
        @pointermove="moveDrag"
        @pointerup="endDrag"
        @pointercancel="endDrag"
      />
      <circle class="mic-gate__handle" :cx="handle.x" :cy="handle.y" r="3" />
    </svg>
    <button
      class="v-side"
      type="button"
      :aria-pressed="!props.muted"
      :title="props.muted ? 'Unmute' : 'Mute'"
      @click="emit('update:muted', !props.muted)"
    >
      <svg class="v-i" viewBox="0 0 24 24" aria-hidden="true"><use :href="props.muted ? '#i-mic-off' : '#i-mic'" /></svg>
    </button>
  </div>
</template>
