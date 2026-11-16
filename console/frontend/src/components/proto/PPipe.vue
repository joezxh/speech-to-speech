<template>
  <div class="pipe">
    <div
      v-for="step in steps"
      :key="step.key"
      class="stage"
      :class="step.state === 'active' ? 'current' : step.state === 'done' ? 'done' : 'pending'"
    >
      <div class="node">{{ step.state === 'done' ? '✓' : '' }}</div>
      <div class="s-label">{{ step.label }}</div>
      <div v-if="step.sub" class="s-sub">{{ step.sub }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
export interface PipeStep {
  key: string
  label: string
  sub?: string
  state: 'done' | 'active' | 'todo'
}

defineProps<{ steps: PipeStep[] }>()
</script>
