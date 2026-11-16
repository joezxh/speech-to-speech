<template>
  <div class="switch" :class="{ on: modelValue }" role="switch" @click="emit('update:modelValue', !modelValue)"></div>
</template>

<script setup lang="ts">
defineProps<{ modelValue: boolean }>()

const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()
</script>
