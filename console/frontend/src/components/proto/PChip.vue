<template>
  <div class="chips">
    <button
      v-for="item in items"
      :key="item.key"
      type="button"
      class="chip"
      :class="{ active: item.key === modelValue }"
      @click="emit('update:modelValue', item.key)"
    >
      {{ item.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  items: { key: string; label: string }[]
  modelValue: string
}>()

const emit = defineEmits<{ (e: 'update:modelValue', key: string): void }>()
</script>
