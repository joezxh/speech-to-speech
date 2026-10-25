<script setup lang="ts">
import { computed } from 'vue'

import type { TurnLatency } from '../types'
import { statusLabel, timingNote, timingRows, timingSummary } from '../useTurnLatency'

const props = defineProps<{ latency: TurnLatency }>()

const summary = computed(() => timingSummary(props.latency))
const rows = computed(() => timingRows(props.latency))
const note = computed(() => timingNote(props.latency))
</script>

<template>
  <details class="hist-timings">
    <summary>{{ summary }}</summary>
    <p class="timing-status">{{ statusLabel(latency.status) }}</p>
    <dl>
      <template v-for="row in rows" :key="row.label">
        <dt>{{ row.label }}</dt>
        <dd>{{ row.value }}</dd>
      </template>
    </dl>
    <p>{{ note }}</p>
  </details>
</template>
