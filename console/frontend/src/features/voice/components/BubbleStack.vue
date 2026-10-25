<script setup lang="ts">
import type { Bubble } from '../types'

const props = defineProps<{ items: Bubble[] }>()
</script>

<template>
  <div class="v-bubbles" aria-live="polite" aria-atomic="false">
    <TransitionGroup name="v-bubble">
      <div v-for="item in props.items" :key="item.id" class="v-bubble" :class="`v-bubble--${item.role}`">
        <span class="v-bubble__role">
          {{ item.role === 'tool' ? 'tool' : item.role === 'user' ? 'You' : 'Assistant' }}
        </span>
        <span class="v-bubble__text">{{ item.text }}</span>
      </div>
    </TransitionGroup>
  </div>
</template>
