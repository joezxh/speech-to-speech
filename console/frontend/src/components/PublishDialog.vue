<script setup lang="ts">
import { ref } from 'vue'

import { AppError } from '@/api/client'
import { publishProfile } from '@/api/profiles'
import DiffTable from '@/components/DiffTable.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import type { PublishResult } from '@/types/profile'

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
    error.value = caught instanceof AppError ? caught : new AppError('unknown', '发布失败')
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
  <a-modal :open="open" title="发布" :footer="null" :mask-closable="!pending" @cancel="close">
    <a-alert
      type="warning"
      show-icon
      message="发布会重启 pipeline 进程"
      description="正在进行的语音会话会中断，并在重连后使用新配置。"
    />

    <DiffTable :draft="draft" :masked="masked" />

    <a-textarea v-model:value="note" :rows="2" placeholder="变更说明（会写进版本记录与审计）" />

    <ErrorBanner :error="error" />

    <a-alert
      v-if="result"
      type="success"
      show-icon
      :message="`v${result.version} 已生效`"
      :description="`耗时 ${result.durationS}s · 池大小 ${result.healthcheck.poolSize ?? '—'} · 审计 ${result.auditId}`"
    />

    <div class="publish-dialog__actions">
      <a-button :disabled="pending" @click="close">{{ result ? '关闭' : '取消' }}</a-button>
      <a-button v-if="!result" type="primary" danger :loading="pending" @click="submit">
        确认发布
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
