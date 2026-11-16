<template>
  <div class="split">
    <i class="p" :style="{ width: aPct + '%' }"></i>
    <i class="c" :style="{ width: 100 - aPct + '%' }"></i>
  </div>
</template>

<script setup lang="ts">
defineProps<{ aPct: number }>()
</script>
