<script setup lang="ts">
import type { TranscriptEntry } from '../types'
import TranscriptList from './TranscriptList.vue'

const props = defineProps<{ open: boolean; entries: TranscriptEntry[] }>()
const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'replay', playing: boolean): void
}>()
</script>

<template>
  <a-drawer
    :open="props.open"
    placement="right"
    :width="380"
    :body-style="{ padding: '0 12px 12px' }"
    @close="emit('update:open', false)"
  >
    <template #title>Conversation</template>
    <TranscriptList :entries="props.entries" @replay="emit('replay', $event)" />
    <p v-if="!props.entries.length" class="v-empty">Nothing said yet.</p>
  </a-drawer>
</template>
