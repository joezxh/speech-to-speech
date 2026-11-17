<script setup lang="ts">
import { computed } from 'vue'

import { trendPath, type TrendPoint } from '@/views/traffic.viewmodel'

const props = defineProps<{ points: TrendPoint[] }>()
const geometry = computed(() => trendPath(props.points, 600, 120))
</script>

<template>
  <svg class="trend-svg" viewBox="0 0 600 120" preserveAspectRatio="none" role="img" aria-label="token trend">
    <path :d="geometry.area" class="trend-area" />
    <path :d="geometry.line" class="trend-line" />
    <circle v-if="points.length" :cx="geometry.peak.x" :cy="geometry.peak.y" r="3" class="trend-peak" />
  </svg>
</template>

<style scoped lang="less">
.trend-svg { width: 100%; height: 120px; }
.trend-area { fill: var(--accent-soft); }
.trend-line { fill: none; stroke: var(--accent); stroke-width: 1.5; }
.trend-peak { fill: var(--warn); }
</style>
