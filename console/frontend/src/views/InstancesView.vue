<script setup lang="ts">
import { ref, watch } from 'vue'

import { AppError } from '@/api/client'
import { getInstances } from '@/api/instances'
import InstanceCard from '@/components/InstanceCard.vue'
import { usePolling } from '@/composables/usePolling'
import { useConsoleStore } from '@/stores/console'
import type { InstanceSnapshot } from '@/types/api'

const consoleStore = useConsoleStore()

const snapshot = ref<InstanceSnapshot | null>(null)
const error = ref('')

async function poll(): Promise<void> {
  try {
    snapshot.value = await getInstances(consoleStore.profile)
    error.value = ''
  } catch (caught) {
    snapshot.value = null
    error.value = caught instanceof AppError ? caught.message : '实例状态不可读'
  }
}

const { active, start, stop } = usePolling(poll, 5000)

watch(
  () => consoleStore.profile,
  () => start(),
  { immediate: true }
)
</script>

<template>
  <div class="instances">
    <div class="instances__bar">
      <a-badge :status="active ? 'processing' : 'default'" :text="active ? '每 5s 刷新' : '已暂停'" />
      <a-button size="small" @click="active ? stop() : start()">{{ active ? '暂停' : '继续' }}</a-button>
    </div>

    <InstanceCard :snapshot="snapshot" :error="error" />
  </div>
</template>

<style scoped lang="less">
.instances {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__bar {
    align-items: center;
    display: flex;
    gap: 12px;
  }
}
</style>
