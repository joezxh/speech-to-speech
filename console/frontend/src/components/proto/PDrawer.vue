<template>
  <div class="drawer" :class="{ open }">
    <div class="drawer-head">
      <h3>{{ title }}</h3>
      <button type="button" class="x-btn" @click="emit('close')">×</button>
    </div>
    <div class="drawer-body">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ open: boolean; title: string }>()

const emit = defineEmits<{ (e: 'close'): void }>()
</script>
