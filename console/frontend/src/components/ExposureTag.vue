<script setup lang="ts">
import { computed } from 'vue'

import type { Exposure } from '@/types/catalog'

const props = defineProps<{ exposure: Exposure }>()

const color = computed(
  () => ({ basic: 'green', advanced: 'blue', expert: 'orange', ops: 'red' })[props.exposure] ?? 'default'
)
</script>

<template>
  <a-tag :color="color">{{ exposure }}</a-tag>
</template>
