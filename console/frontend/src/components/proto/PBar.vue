<template>
  <div class="bar" :title="title">
    <i :style="{ width: clamped + '%' }"></i>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ pct: number; warnAbove?: number }>(), { warnAbove: 100 })

const clamped = computed(() => Math.max(0, Math.min(100, props.pct)))
const title = computed(() => (props.pct > props.warnAbove ? `超过阈值 ${props.warnAbove}%（当前 ${props.pct}%）` : `${props.pct}%`))
</script>
