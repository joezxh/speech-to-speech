<template>
  <div class="kpi" :class="tone ? `tone-${tone}` : ''">
    <div class="label">{{ label }}</div>
    <div class="value">{{ value }}</div>
    <div v-if="sub" class="sub">{{ sub }}</div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  label: string
  value: string | number
  sub?: string
  tone?: 'ok' | 'warn' | 'bad' | 'accent'
}>()
</script>

<style scoped>
.kpi.tone-ok .value {
  color: var(--s2s-color-success);
}
.kpi.tone-warn .value {
  color: var(--s2s-color-warning);
}
.kpi.tone-bad .value {
  color: var(--s2s-color-danger);
}
.kpi.tone-accent .value {
  color: var(--s2s-color-accent);
}
</style>
