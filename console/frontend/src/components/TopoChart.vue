<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { TopoLayout, TopoTone } from '@/utils/topoLayout'

/**
 * 拓扑渲染（原型 topoSVG）：左侧 LB 盒 → 机器行 → 右侧 Pipeline 实例 chip。
 * 机器可点/可键盘激活，跳部署参数页由父组件决定（emit machine）。
 * 颜色一律走 --s2s-* 变量，本文件已进 hex-ban ratchet。
 */
const props = defineProps<{ layout: TopoLayout }>()
const emit = defineEmits<{ machine: [host: string] }>()
const { t } = useI18n()

const LB_W = 180
const LB_H = 76
const MX_X = 300
const MX_W = 200
const MX_H = 64
const CHIP_W = 120
const CHIP_H = 30

const TONE_VAR: Record<TopoTone, string> = {
  ok: 'var(--s2s-color-success)',
  warn: 'var(--s2s-color-warning)',
  draining: 'var(--s2s-color-warning)',
  bad: 'var(--s2s-color-danger)',
  muted: 'var(--s2s-color-muted)'
}

const POLICIES = ['least', 'rr', 'lat']
const policyLabel = (policy: string): string =>
  POLICIES.includes(policy) ? t(`overview.policy.${policy}`) : policy

const occupancy = (inUse: number | null, size: number | null): string =>
  t('overview.topology.occupancy', {
    inUse: inUse ?? '—',
    size: size ?? '—'
  })
</script>

<template>
  <svg
    class="topo"
    :viewBox="`0 0 ${props.layout.width} ${props.layout.height}`"
    role="img"
    :aria-label="t('overview.topology.title')"
  >
    <path
      v-for="(edge, index) in props.layout.edges"
      :key="`edge-${index}`"
      :d="edge.d"
      :class="['topo__edge', { 'is-flow': edge.flow }]"
    />

    <!-- LB：集群名 / registry · policy / /v1/pool · 活跃会话 -->
    <rect
      class="topo__lb-box"
      :x="props.layout.lb.x"
      :y="props.layout.lb.y"
      :width="LB_W"
      :height="LB_H"
      rx="10"
    />
    <text class="topo__t-lg" :x="props.layout.lb.x + 20" :y="props.layout.lb.y + 30">
      {{ props.layout.lb.cluster || '—' }}
    </text>
    <text class="topo__t-sm" :x="props.layout.lb.x + 20" :y="props.layout.lb.y + 50">
      {{ props.layout.lb.registry || '—' }} · {{ policyLabel(props.layout.lb.policy) }}
    </text>
    <text class="topo__t-sm" :x="props.layout.lb.x + 20" :y="props.layout.lb.y + 66">
      {{ t('overview.topology.poolSessions', { n: props.layout.lb.sessions ?? '—' }) }}
    </text>

    <!-- 空集群：LB 之下给空态文案，不留白也不画假机器 -->
    <text v-if="props.layout.empty" class="topo__empty" :x="MX_X" :y="props.layout.lb.y + 40">
      {{ t('overview.topology.empty') }}
    </text>

    <!-- 机器行 + 实例 chip -->
    <g
      v-for="machine in props.layout.machines"
      :key="machine.id"
      class="topo__machine"
      :data-machine="machine.host"
      role="button"
      tabindex="0"
      :aria-label="machine.host"
      @click="emit('machine', machine.host)"
      @keydown.enter="emit('machine', machine.host)"
    >
      <rect class="topo__mx-box" :x="MX_X" :y="machine.y" :width="MX_W" :height="MX_H" rx="8" />
      <text class="topo__t-md" :x="MX_X + 14" :y="machine.y + 24">
        {{ machine.label || machine.host }}
      </text>
      <text class="topo__t-sm" :x="MX_X + 14" :y="machine.y + 40">
        {{ machine.models.length ? machine.models.join(' / ') : machine.host }}
      </text>
      <text class="topo__t-sm" :x="MX_X + 14" :y="machine.y + 56">
        {{ t('overview.topology.machineMeta', { n: machine.instanceCount, m: machine.onlineCount }) }}
      </text>
      <circle
        :cx="MX_X + MX_W - 14"
        :cy="machine.y + 20"
        r="4"
        :fill="TONE_VAR[machine.tone]"
      />
    </g>

    <g v-for="chip in props.layout.machines.flatMap((m) => m.chips)" :key="chip.id">
      <rect
        class="topo__chip"
        :class="`is-${chip.tone}`"
        :x="chip.x"
        :y="chip.y"
        :width="CHIP_W"
        :height="CHIP_H"
        rx="6"
        :stroke="TONE_VAR[chip.tone]"
      />
      <text class="topo__t-sm" :x="chip.x + 8" :y="chip.y + 13">{{ chip.label }}</text>
      <text class="topo__t-sm" :x="chip.x + 8" :y="chip.y + 25">
        {{ occupancy(chip.inUse, chip.size) }}
      </text>
    </g>
  </svg>
</template>

<style scoped lang="less">
.topo {
  width: 100%;
  height: auto;
  display: block;

  text {
    font-family: var(--s2s-font-mono);
    fill: var(--s2s-color-text);
  }

  &__t-sm {
    font-size: 9.5px;
    fill: var(--s2s-color-muted);
  }

  &__t-md {
    font-size: 11.5px;
  }

  &__t-lg {
    font-size: 13px;
    font-weight: 600;
  }

  &__lb-box {
    fill: var(--s2s-color-surface-2);
    stroke: var(--s2s-color-accent);
    stroke-width: 1.4;
  }

  &__mx-box {
    fill: var(--s2s-color-surface-2);
    stroke: var(--s2s-color-border);
  }

  &__chip {
    fill: var(--s2s-color-surface-2);
    stroke-width: 1;
  }

  &__edge {
    stroke: var(--s2s-color-border);
    stroke-width: 1.2;
    fill: none;

    &.is-flow {
      stroke: var(--s2s-color-accent);
      stroke-dasharray: 5 5;
      animation: topo-dash 1.4s linear infinite;
    }
  }

  &__machine {
    cursor: pointer;

    &:hover .topo__mx-box {
      stroke: var(--s2s-color-accent);
    }

    &:focus-visible .topo__mx-box {
      stroke: var(--s2s-color-accent);
      stroke-width: 2.5;
    }
  }

  &__empty {
    fill: var(--s2s-color-muted);
    font-family: var(--s2s-font-mono);
    font-size: 12px;
  }
}

@keyframes topo-dash {
  to {
    stroke-dashoffset: -10;
  }
}

@media (prefers-reduced-motion: reduce) {
  .topo__edge.is-flow {
    animation: none;
  }
}
</style>
