<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

import { AppError } from '@/api/client'
import { getInstances } from '@/api/instances'
import InstanceCard from '@/components/InstanceCard.vue'
import RuntimeGrid from '@/components/RuntimeGrid.vue'
import { usePolling } from '@/composables/usePolling'
import { useConsoleStore } from '@/stores/console'
import { useRuntimeStore } from '@/stores/runtime'
import type { InstanceSnapshot } from '@/types/api'

const consoleStore = useConsoleStore()
const runtime = useRuntimeStore()

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

const { active, start: startInstances, stop: stopInstances } = usePolling(poll, 5000)

/**
 * 两个端点各有各的节奏，但只有一个「暂停」按钮：停一半会让徽标说谎。
 * `/instances` 说容器，`/runtime/models` 说模型，一起刷新一起停。
 */
function startAll(): void {
  startInstances()
  runtime.startPolling(consoleStore.profile)
}

function stopAll(): void {
  stopInstances()
  runtime.stopPolling()
}

watch(() => consoleStore.profile, startAll, { immediate: true })

/**
 * §3.9.1 第 4 条：页签切走就停。console 与 pipeline 同容器，一个被遗忘的
 * 后台标签页每 5s 跑一次 `nvidia-smi` 加一次日志尾读，是这个面板唯一可能
 * 伤到语音的地方。
 */
function onVisibility(): void {
  if (document.hidden) stopAll()
  else startAll()
}

document.addEventListener('visibilitychange', onVisibility)

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', onVisibility)
  stopAll()
})
</script>

<template>
  <div class="instances">
    <div class="instances__bar">
      <a-badge :status="active ? 'processing' : 'default'" :text="active ? '每 5s 刷新' : '已暂停'" />
      <a-button size="small" @click="active ? stopAll() : startAll()">
        {{ active ? '暂停' : '继续' }}
      </a-button>
    </div>

    <RuntimeGrid :snapshot="runtime.snapshot" :loading="runtime.loading" :error="runtime.error" />

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
