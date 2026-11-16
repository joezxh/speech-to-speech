<template>
  <svg class="wave" :viewBox="`0 0 ${viewWidth} 76`" preserveAspectRatio="none">
    <rect
      v-for="(bar, index) in bars"
      :key="index"
      class="bar-in"
      :x="index * BAR_STEP + 2"
      :y="76 - bar"
      width="6"
      :height="Math.max(bar, 1)"
      rx="1"
    />
    <rect
      v-if="window"
      class="win"
      :x="window[0] * BAR_STEP"
      y="0"
      :width="(window[1] - window[0]) * BAR_STEP"
      height="76"
    />
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ bars: number[]; window?: [number, number] }>(), { bars: () => [] })

const BAR_STEP = 9
const viewWidth = computed(() => Math.max(props.bars.length * BAR_STEP + 4, 120))
</script>
