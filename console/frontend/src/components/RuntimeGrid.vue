<script setup lang="ts">
import { computed } from 'vue'

import ModelRuntimeCard from '@/components/ModelRuntimeCard.vue'
import { describeAlert } from '@/utils/error'
import { DASH, formatTime } from '@/utils/format'
import { gpuHeadline } from '@/utils/runtime-view'
import type { RuntimeSnapshot } from '@/types/runtime'

const props = defineProps<{ snapshot: RuntimeSnapshot | null; loading: boolean; error: string }>()

const gpu = computed(() => props.snapshot?.gpu ?? null)
const stages = computed(() => props.snapshot?.stages ?? [])

/**
 * `vram_pressure` 的阈值是 90%（A.14），分级只影响进度条颜色：
 * 到线了才变红，其余时间不喊狼来了。
 */
const barLevel = computed<'ok' | 'warn' | 'bad'>(() => {
  const percent = props.snapshot?.gpu.percent ?? 0
  if (percent >= 90) return 'bad'
  if (percent >= 75) return 'warn'
  return 'ok'
})
</script>

<template>
  <section class="runtime">
    <div class="runtime__head">
      <span class="runtime__title">模型运行时</span>
      <span class="runtime__gpu">{{ gpuHeadline(gpu) }}</span>
      <span class="runtime__meta">
        <template v-if="snapshot">
          采样于 {{ formatTime(snapshot.collectedAt) }} · 窗口 {{ snapshot.windowS }}s
        </template>
        <template v-else>{{ loading ? '采样中…' : DASH }}</template>
      </span>
    </div>

    <div v-if="gpu?.available" class="rt-bar" :data-level="barLevel">
      <span class="rt-bar__fill" :style="{ width: `${Math.min(gpu.percent ?? 0, 100)}%` }" />
    </div>

    <a-alert v-if="error" type="error" show-icon :message="error" />

    <!--
      这里的 alerts 说“模型”，InstanceCard 的 alerts 说“容器”（A.10/A.14），
      两套语义不合并。
    -->
    <a-alert
      v-for="alert in snapshot?.alerts ?? []"
      :key="alert"
      type="warning"
      show-icon
      :message="describeAlert(alert)"
    />

    <a-skeleton v-if="!stages.length && loading" active :paragraph="{ rows: 4 }" />

    <div v-else-if="stages.length" class="runtime__grid">
      <ModelRuntimeCard v-for="stage in stages" :key="stage.stage" :stage="stage" :gpu="gpu" />
    </div>

    <a-empty v-else description="还没有模型运行时数据" />
  </section>
</template>

<style scoped lang="less">
.runtime {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__head {
    align-items: baseline;
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
  }

  &__title {
    font-size: 14px;
    font-weight: 600;
  }

  &__gpu {
    color: #c8cede;
    font-size: 13px;
  }

  &__meta {
    color: #8b93a7;
    font-size: 12px;
    margin-left: auto;
  }

  &__grid {
    display: grid;
    gap: 12px;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  }
}

.rt-bar {
  background: #1c2130;
  border-radius: 4px;
  height: 6px;
  overflow: hidden;
  width: 100%;
}

.rt-bar__fill {
  background: #34d399;
  display: block;
  height: 100%;
}

.rt-bar[data-level='warn'] .rt-bar__fill {
  background: #f59e0b;
}

.rt-bar[data-level='bad'] .rt-bar__fill {
  background: #ff6a75;
}
</style>
