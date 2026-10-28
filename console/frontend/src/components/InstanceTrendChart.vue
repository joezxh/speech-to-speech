<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { InstanceMetricPoint } from '@/types/api'
import { dedupeByLatestObserver } from '@/utils/instances-view'

/**
 * 只读趋势：容量/空闲/探测耗时三条线。槽位数与探测毫秒量级不同，各自按
 * 自己的最大值归一化到同一 viewBox 高度，不做跨量纲对齐（面板只给形状与相对趋势）。
 * 不引入图表库——沿用仓内手写 SVG 路线（spec §14）。
 */
const props = defineProps<{ points: InstanceMetricPoint[] }>()
const { t } = useI18n()

const W = 600
const H = 160
const PAD = 8

// 跨 console 先去重，避免同一实例同时刻被两台 console 采样而 ×N（spec §10）。
const series = computed(() => dedupeByLatestObserver(props.points))

function toLine(pick: (point: InstanceMetricPoint) => number | null): string {
  const values = series.value.map(pick)
  const present = values.filter((v): v is number => v !== null && Number.isFinite(v))
  if (!present.length || series.value.length < 2) return ''
  const max = Math.max(...present)
  const span = max > 0 ? max : 1
  const stepX = (W - PAD * 2) / (series.value.length - 1)
  return values
    .map((value, index) => {
      if (value === null || !Number.isFinite(value)) return ''
      const x = PAD + index * stepX
      const y = H - PAD - (value / span) * (H - PAD * 2)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .filter(Boolean)
    .join(' ')
}

const sizeLine = computed(() => toLine((p) => p.size))
const freeLine = computed(() => toLine((p) => p.free))
const probeLine = computed(() => toLine((p) => p.probeMs))
const single = computed(() => series.value.length < 2)
</script>

<template>
  <div class="trend">
    <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" role="img" :aria-label="t('machines.trend.ariaLabel')">
      <polyline :points="sizeLine" fill="none" stroke="#4a90d9" stroke-width="1.5" />
      <polyline :points="freeLine" fill="none" stroke="#3fb950" stroke-width="1.5" />
      <polyline :points="probeLine" fill="none" stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="4 3" />
    </svg>
    <div v-if="single" class="trend__hint">{{ t('machines.trend.hint') }}</div>
    <ul class="trend__legend">
      <li><span class="trend__key" style="background: #4a90d9" />{{ t('machines.trend.legend.capacity') }}</li>
      <li><span class="trend__key" style="background: #3fb950" />{{ t('machines.trend.legend.free') }}</li>
      <li><span class="trend__key" style="background: #f59e0b" />{{ t('machines.trend.legend.probe') }}</li>
    </ul>
  </div>
</template>

<style scoped lang="less">
.trend {
  display: flex;
  flex-direction: column;
  gap: 6px;

  svg {
    background: #141a2e;
    border-radius: 8px;
    height: 160px;
    width: 100%;
  }

  &__hint {
    color: #8b93a7;
    font-size: 12px;
  }

  &__legend {
    color: #8b93a7;
    display: flex;
    font-size: 12px;
    gap: 16px;
    list-style: none;
    margin: 0;
    padding: 0;
  }

  &__key {
    border-radius: 2px;
    display: inline-block;
    height: 8px;
    margin-right: 6px;
    width: 12px;
  }
}
</style>
