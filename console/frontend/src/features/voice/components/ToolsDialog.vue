<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { useToolsStore } from '@/stores/tools'

const props = defineProps<{
  open: boolean
  camera: boolean
}>()
const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'update:camera', value: boolean): void
  (e: 'toolsChanged'): void
}>()

const { t } = useI18n()
const tools = useToolsStore()

async function toggle(id: string, value: boolean): Promise<void> {
  await tools.toggle(id, value)
  emit('toolsChanged')
}
</script>

<template>
  <a-modal :open="props.open" :title="t('nav.tools')" :footer="null" @cancel="emit('update:open', false)">
    <p class="v-hint">{{ t('tools.page.desc') }}</p>

    <div v-for="row in tools.rows" :key="row.id" class="v-tool">
      <div class="v-tool__info">
        <span class="v-tool__name">{{ row.name }}</span>
        <span class="v-tool__desc">{{ row.description }}</span>
      </div>
      <a-switch :checked="tools.isEnabled(row)" @change="(value: boolean) => toggle(row.id, value)" />
    </div>

    <div class="v-tool v-tool--sep">
      <div class="v-tool__info">
        <span class="v-tool__name">Camera</span>
        <span class="v-tool__desc">Let the assistant see through your webcam.</span>
      </div>
      <a-switch :checked="props.camera" @change="(value: boolean) => emit('update:camera', value)" />
    </div>
  </a-modal>
</template>
