<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { trendPath, type TrendPoint } from '@/views/traffic.viewmodel'

const props = defineProps<{ points: TrendPoint[] }>()
const { t } = useI18n()

const geometry = computed(() => trendPath(props.points, 600, 120))
const peakTotal = computed(() => (props.points.length ? Math.max(...props.points.map((p) => p.total)) : 0))
const lastTotal = computed(() => (props.points.length ? props.points[props.points.length - 1].total : 0))
</script>

<template>
  <svg class="trend" viewBox="0 0 600 120" preserveAspectRatio="none" role="img" aria-label="trend">
    <path :d="geometry.area" class="area" />
    <path :d="geometry.line" class="line" />
    <template v-if="points.length">
      <circle :cx="geometry.peak.x" :cy="geometry.peak.y" r="3" class="peak" />
      <text :x="geometry.peak.x - 6" :y="geometry.peak.y - 6" text-anchor="end" class="t-sm">
        {{ t('traffic.chart.peak') }} {{ peakTotal }}
      </text>
      <circle :cx="geometry.last.x" :cy="geometry.last.y" r="4" class="now" />
      <text :x="geometry.last.x" :y="geometry.last.y - 8" text-anchor="end" class="t-sm">
        {{ t('traffic.chart.now') }} {{ lastTotal }}
      </text>
    </template>
  </svg>
</template>

<style scoped lang="less">
.trend {
  width: 100%;
  height: 120px;
  display: block;
  .peak { fill: var(--s2s-color-warning); }
  .now { fill: var(--s2s-color-accent); }
  .line { stroke-width: 1.5; }
}
</style>
