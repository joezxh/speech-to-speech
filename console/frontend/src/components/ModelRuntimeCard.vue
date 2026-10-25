<script setup lang="ts">
import { computed } from 'vue'

import { DASH } from '@/utils/format'
import {
  STAGE_LABEL,
  busyText,
  firstByteText,
  latencyText,
  loadLabel,
  modelText,
  queueText,
  vramText
} from '@/utils/runtime-view'
import type { GpuInfo, RuntimeStage } from '@/types/runtime'

const props = defineProps<{ stage: RuntimeStage; gpu: GpuInfo | null }>()

/**
 * 显存是**整卡**峰值（`resources.vram_used_mb_peak`，采样线程按设备聚合），
 * 四段共用一张卡。把 VAD 卡写成一个独占数字，会让人以为 VAD 自己吃了 18 GB，
 * 所以数字旁常驻一个「整卡」提示，和 `vram_not_attributable` 一个意思。
 */
const vramHint = computed(() =>
  props.gpu?.available && props.gpu.totalMb
    ? `调用期间的整卡峰值（含同卡其它进程），不是该模型独占量；整卡 ${props.gpu.totalMb} MB`
    : '调用期间的整卡峰值（含同卡其它进程），不是该模型独占量'
)
</script>

<template>
  <a-card
    size="small"
    class="rt-card"
    :class="{ 'is-down': !stage.loaded }"
    :data-loaded="String(stage.loaded)"
  >
    <template #title>
      <span class="rt-card__stage">{{ STAGE_LABEL[stage.stage] }}</span>
      <a-tag :color="stage.loaded ? 'green' : 'red'">{{ loadLabel(stage.loaded) }}</a-tag>
    </template>

    <p class="rt-card__model">{{ modelText(stage) }}</p>
    <p class="rt-card__backend">{{ stage.backend ?? DASH }}</p>

    <dl class="rt-card__grid">
      <dt>VRAM</dt>
      <dd>
        {{ vramText(stage) }}
        <a-tooltip :title="vramHint"><span class="rt-card__hint">整卡</span></a-tooltip>
      </dd>

      <dt>Busy</dt>
      <dd>{{ busyText(stage) }}</dd>

      <dt>Queue</dt>
      <dd>{{ queueText(stage) }}</dd>

      <dt>First byte</dt>
      <dd>{{ firstByteText(stage) }}</dd>

      <dt>p50 / p95</dt>
      <dd>
        {{ latencyText(stage) }}
        <span class="rt-card__hint">取自观测窗口</span>
      </dd>
    </dl>
  </a-card>
</template>

<style scoped lang="less">
.rt-card {
  height: 100%;

  &.is-down {
    opacity: 0.85;
  }

  &__stage {
    font-weight: 600;
    margin-right: 8px;
  }

  &__model {
    font-size: 13px;
    margin: 0 0 2px;
    overflow-wrap: anywhere;
  }

  &__backend {
    color: #8b93a7;
    font-size: 12px;
    margin: 0 0 10px;
  }

  &__grid {
    display: grid;
    font-size: 12px;
    gap: 6px 12px;
    grid-template-columns: 76px minmax(0, 1fr);
    margin: 0;

    dt {
      color: #8b93a7;
    }

    dd {
      margin: 0;
      overflow-wrap: anywhere;
    }
  }

  &__hint {
    color: #6d7688;
    font-size: 11px;
    margin-left: 6px;
  }
}
</style>
