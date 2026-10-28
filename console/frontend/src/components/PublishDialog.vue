<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { AppError } from '@/api/client'
import { publishProfile } from '@/api/profiles'
import DiffTable from '@/components/DiffTable.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import type { PublishResult } from '@/types/profile'

const { t } = useI18n()
const props = defineProps<{
  open: boolean
  profile: string
  baseVersion: number | null
  draft: Record<string, unknown>
  masked: string[]
}>()
const emit = defineEmits<{ close: []; published: [result: PublishResult] }>()

const note = ref('')
const pending = ref(false)
const error = ref<AppError | null>(null)
const result = ref<PublishResult | null>(null)

async function submit(): Promise<void> {
  error.value = null
  result.value = null
  pending.value = true
  try {
    result.value = await publishProfile(props.profile, {
      baseVersion: props.baseVersion,
      note: note.value
    })
    note.value = ''
    emit('published', result.value)
  } catch (caught) {
    error.value = caught instanceof AppError ? caught : new AppError('unknown', t('release.publish.failed'))
  } finally {
    pending.value = false
  }
}

function close(): void {
  if (pending.value) return // 一次发布中途关掉对话框，用户会以为它被取消了
  result.value = null
  error.value = null
  emit('close')
}
</script>

<template>
  <a-modal :open="open" :title="t('release.publish.title')" :footer="null" :mask-closable="!pending" @cancel="close">
    <a-alert
      type="warning"
      show-icon
      :message="t('release.publish.alertMessage')"
      :description="t('release.publish.alertDescription')"
    />

    <DiffTable :draft="draft" :masked="masked" />

    <a-textarea v-model:value="note" :rows="2" :placeholder="t('release.publish.notePlaceholder')" />

    <ErrorBanner :error="error" />

    <a-alert
      v-if="result"
      type="success"
      show-icon
      :message="t('release.publish.publishedMessage', { version: result.version })"
      :description="t('release.publish.publishedDescription', { duration: result.durationS, poolSize: result.healthcheck.poolSize ?? '—', auditId: result.auditId })"
    />

    <div class="publish-dialog__actions">
      <a-button :disabled="pending" @click="close">{{ result ? t('release.publish.close') : t('release.publish.cancel') }}</a-button>
      <a-button v-if="!result" type="primary" danger :loading="pending" @click="submit">
        {{ t('release.publish.confirm') }}
      </a-button>
    </div>
  </a-modal>
</template>

<style scoped lang="less">
.publish-dialog__actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
