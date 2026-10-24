<script setup lang="ts">
import { ref, watch } from 'vue'

import { AppError } from '@/api/client'
import { getAudit } from '@/api/profiles'
import AuditTable from '@/components/AuditTable.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import { useConsoleStore } from '@/stores/console'
import type { AuditRow } from '@/types/profile'

const consoleStore = useConsoleStore()

const rows = ref<AuditRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const loading = ref(false)
const error = ref<AppError | null>(null)

const actor = ref('')
const action = ref('')
const result = ref('')
const field = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const data = await getAudit(consoleStore.profile, {
      actor: actor.value || undefined,
      action: action.value || undefined,
      result: result.value || undefined,
      field: field.value || undefined,
      page: page.value,
      pageSize: pageSize.value
    })
    rows.value = data.list
    total.value = data.total
  } catch (caught) {
    error.value = caught instanceof AppError ? caught : new AppError('unknown', '审计列表加载失败')
    rows.value = []
  } finally {
    loading.value = false
  }
}

watch([() => consoleStore.profile, page, pageSize], () => void load(), { immediate: true })
</script>

<template>
  <div class="audit">
    <form class="audit__filters" @submit.prevent="page = 1; void load()">
      <a-input v-model:value="actor" placeholder="操作人" allow-clear />
      <a-input v-model:value="action" placeholder="动作（如 draft.patch）" allow-clear />
      <a-select
        v-model:value="result"
        :options="[
          { value: '', label: '全部结果' },
          { value: 'ok', label: 'ok' },
          { value: 'failed', label: 'failed' }
        ]"
      />
      <a-input v-model:value="field" placeholder="字段名（如 vad.min_silence_ms）" allow-clear />
      <a-button type="primary" html-type="submit">查询</a-button>
    </form>

    <ErrorBanner :error="error" />
    <AuditTable :rows="rows" :loading="loading" />
    <a-pagination
      v-model:current="page"
      v-model:page-size="pageSize"
      :total="total"
      size="small"
      show-size-changer
      :page-size-options="['50', '100', '200']"
    />
  </div>
</template>

<style scoped lang="less">
.audit {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__filters {
    display: flex;
    gap: 8px;
    max-width: 900px;
  }
}
</style>
