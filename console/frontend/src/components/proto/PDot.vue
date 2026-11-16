<template>
  <span class="dot" :class="state"></span>
</template>

<script setup lang="ts">
defineProps<{ state: 'ok' | 'warn' | 'draining' | 'bad' }>()
</script>
