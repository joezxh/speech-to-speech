<script setup lang="ts">
import { computed } from 'vue'

import type { VoiceState } from '../types'

const props = defineProps<{ state: VoiceState; position: number; expiresSec: number; full: boolean }>()
const emit = defineEmits<{ (e: 'join'): void; (e: 'leave'): void }>()

const yourTurn = computed(() => props.state === 'your-turn')
const visible = computed(() => props.state === 'queued' || yourTurn.value || props.full)
</script>

<template>
  <div v-if="visible" class="v-queue" role="status">
    <p v-if="props.full" class="v-queue__body">The waiting line is full. Try again in a minute.</p>
    <p v-else-if="yourTurn" class="v-queue__body">A slot opened up. Join within {{ props.expiresSec }}s.</p>
    <p v-else class="v-queue__body">You're number {{ props.position }}. Waiting never uses up your daily minutes.</p>
    <div class="v-queue__actions">
      <a-button v-if="yourTurn" class="v-join" type="primary" size="large" @click="emit('join')">Join now</a-button>
      <a-button v-if="!yourTurn" class="v-leave" size="large" @click="emit('leave')">Leave queue</a-button>
    </div>
  </div>
</template>
