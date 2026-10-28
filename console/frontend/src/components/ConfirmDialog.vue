<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineProps<{ open: boolean; title: string; content: string; danger?: boolean }>()
const emit = defineEmits<{ answer: [confirmed: boolean] }>()
const { t } = useI18n()
</script>

<template>
  <a-modal :open="open" :title="title" :footer="null" @cancel="emit('answer', false)">
    <p>{{ content }}</p>
    <div class="confirm-dialog__actions">
      <a-button @click="emit('answer', false)">{{ t('common.cancel') }}</a-button>
      <a-button :danger="danger" type="primary" @click="emit('answer', true)">{{ t('common.confirm') }}</a-button>
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
