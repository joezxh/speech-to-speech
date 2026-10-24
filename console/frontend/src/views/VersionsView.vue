<script setup lang="ts">
import { ref, watch } from 'vue'

import { AppError } from '@/api/client'
import { getVersions } from '@/api/profiles'
import ErrorBanner from '@/components/ErrorBanner.vue'
import VersionTable from '@/components/VersionTable.vue'
import { useConsoleStore } from '@/stores/console'
import type { VersionRow } from '@/types/profile'

const consoleStore = useConsoleStore()

const rows = ref<VersionRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref<AppError | null>(null)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const data = await getVersions(consoleStore.profile, page.value, pageSize.value)
    rows.value = data.list
    total.value = data.total
  } catch (caught) {
    error.value = caught instanceof AppError ? caught : new AppError('unknown', '版本列表加载失败')
    rows.value = []
  } finally {
    loading.value = false
  }
}

watch([() => consoleStore.profile, page, pageSize], () => void load(), { immediate: true })
</script>

<template>
  <div class="versions">
    <ErrorBanner :error="error" />
    <VersionTable :rows="rows" :loading="loading" />
    <a-pagination
      v-model:current="page"
      v-model:page-size="pageSize"
      :total="total"
      size="small"
      show-size-changer
      :page-size-options="['20', '50', '100']"
    />
  </div>
</template>

<style scoped lang="less">
.versions {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
</style>
