<template>
  <span class="badge" :class="kind">{{ text }}</span>
</template>

<script setup lang="ts">
export type BadgeKind =
  | 'ok'
  | 'warn'
  | 'bad'
  | 'accent'
  | 'orange'
  | 'hot'
  | 'both'
  | 'container'
  | 'start'
  | 'fixed'
  | 'ro'
  | 'draft'
  | 'equal'
  | 'diff'

defineProps<{ kind: BadgeKind; text: string }>()
</script>
