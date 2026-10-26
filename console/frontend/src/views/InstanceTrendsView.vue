<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { AppError } from '@/api/client'
import { getInstanceMetrics, getInstances } from '@/api/instances'
import ErrorBanner from '@/components/ErrorBanner.vue'
import InstanceTrendChart from '@/components/InstanceTrendChart.vue'
import { useConsoleStore } from '@/stores/console'
import type { InstanceMetricPoint, InstanceRow } from '@/types/api'

/**
 * 「趋势」独立成页（负载均衡菜单组下）：选一台实例，看它的容量/空闲/探测耗时时间线。
 * 从实例管理页跳转时以 `?id=` 预选；直接进页则取列表第一台。取数与去重逻辑沿用
 * `InstanceTrendChart`（内部按 observedBy 去重），本页只负责选择与时间窗。
 */
const consoleStore = useConsoleStore()
const route = useRoute()

const instances = ref<InstanceRow[]>([])
const trendId = ref(String(route.query.id ?? ''))
const actionError = ref<AppError | null>(null)

type Window = '1h' | '6h' | '24h' | '7d'
const WINDOWS: { key: Window; label: string }[] = [
  { key: '1h', label: '1h' },
  { key: '6h', label: '6h' },
  { key: '24h', label: '24h' },
  { key: '7d', label: '7d' }
]
const trendWindow = ref<Window>('1h')
const trendPoints = ref<InstanceMetricPoint[]>([])
const trendLoading = ref(false)

const options = computed(() =>
  instances.value.map((row) => ({ value: row.instance_id, label: row.instance_id }))
)

async function loadInstances(): Promise<void> {
  try {
    const snapshot = await getInstances(consoleStore.profile)
    instances.value = snapshot.instances ?? []
    if (!trendId.value && instances.value.length) trendId.value = instances.value[0].instance_id
    actionError.value = null
  } catch (caught) {
    instances.value = []
    actionError.value =
      caught instanceof AppError ? caught : new AppError('unknown', '实例列表不可读')
  }
}

async function loadTrend(): Promise<void> {
  if (!trendId.value) {
    trendPoints.value = []
    return
  }
  trendLoading.value = true
  actionError.value = null
  try {
    const data = await getInstanceMetrics(trendId.value, trendWindow.value)
    trendPoints.value = data.points
  } catch (caught) {
    trendPoints.value = []
    actionError.value =
      caught instanceof AppError ? caught : new AppError('unknown', '趋势不可读')
  } finally {
    trendLoading.value = false
  }
}

async function reload(): Promise<void> {
  await loadInstances()
  await loadTrend()
}

// 换实例或换时间窗都重新取数；profile 切换时列表与曲线一起重来。
watch([trendId, trendWindow], loadTrend)
watch(
  () => consoleStore.profile,
  () => void reload()
)

onMounted(() => void reload())
</script>

<template>
  <div class="trends">
    <div class="trends__bar">
      <a-select
        v-model:value="trendId"
        size="small"
        class="trends__pick"
        placeholder="选择实例"
        :options="options"
      />
      <a-button-group size="small">
        <a-button
          v-for="item in WINDOWS"
          :key="item.key"
          size="small"
          :type="trendWindow === item.key ? 'primary' : 'default'"
          @click="trendWindow = item.key"
        >
          {{ item.label }}
        </a-button>
      </a-button-group>
      <a-button size="small" :loading="trendLoading" @click="reload">刷新</a-button>
    </div>

    <ErrorBanner :error="actionError" />

    <a-empty v-if="!trendId" description="没有可展示的实例" />
    <a-spin v-else :spinning="trendLoading">
      <InstanceTrendChart :points="trendPoints" />
    </a-spin>
  </div>
</template>

<style scoped lang="less">
.trends {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__bar {
    align-items: center;
    display: flex;
    gap: 12px;
  }

  &__pick {
    width: 200px;
  }
}
</style>
