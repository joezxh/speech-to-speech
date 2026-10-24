<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { AppError } from '@/api/client'
import { getVersions, rollbackProfile } from '@/api/profiles'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ErrorBanner from '@/components/ErrorBanner.vue'
import VersionTable from '@/components/VersionTable.vue'
import { useConfirm } from '@/composables/useConfirm'
import { useConsoleStore } from '@/stores/console'
import type { VersionRow } from '@/types/profile'

const consoleStore = useConsoleStore()
const {
  open: confirmOpen,
  title: confirmTitle,
  content: confirmContent,
  ask: askConfirm,
  answer: answerConfirm
} = useConfirm()

const rows = ref<VersionRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref<AppError | null>(null)
const rollbackError = ref<AppError | null>(null)
/** 当前 live 的那一行不应该有「回滚到它」：它已经是了。 */
const liveVersion = computed(() => rows.value.find((row) => row.status === 'live')?.version ?? null)

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

async function rollback(target: number): Promise<void> {
  const confirmed = await askConfirm({
    title: `回滚到 v${target}`,
    content: '回滚会写入一个新版本并重启 pipeline，正在进行的语音会话会中断。'
  })
  if (!confirmed) return
  rollbackError.value = null
  try {
    await rollbackProfile(consoleStore.profile, { targetVersion: target, note: `rollback to v${target}` })
    await load()
    await consoleStore.refreshStatus()
  } catch (caught) {
    rollbackError.value = caught instanceof AppError ? caught : new AppError('unknown', '回滚失败')
  }
}
</script>

<template>
  <div class="versions">
    <ErrorBanner :error="error" />
    <ErrorBanner :error="rollbackError" />
    <VersionTable :rows="rows" :loading="loading" :live-version="liveVersion" @rollback="rollback" />
    <a-pagination
      v-model:current="page"
      v-model:page-size="pageSize"
      :total="total"
      size="small"
      show-size-changer
      :page-size-options="['20', '50', '100']"
    />

    <ConfirmDialog
      :open="confirmOpen"
      :title="confirmTitle"
      :content="confirmContent"
      danger
      @answer="answerConfirm"
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
