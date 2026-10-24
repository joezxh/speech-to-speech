<script setup lang="ts">
defineProps<{ open: boolean; title: string; content: string; danger?: boolean }>()
const emit = defineEmits<{ answer: [confirmed: boolean] }>()
</script>

<template>
  <a-modal :open="open" :title="title" :footer="null" @cancel="emit('answer', false)">
    <p>{{ content }}</p>
    <div class="confirm-dialog__actions">
      <a-button @click="emit('answer', false)">取消</a-button>
      <a-button :danger="danger" type="primary" @click="emit('answer', true)">确认</a-button>
    </div>
  </a-modal>
</template>

<style scoped lang="less">
.confirm-dialog__actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>
