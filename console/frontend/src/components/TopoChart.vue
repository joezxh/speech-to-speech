<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { TopoLayout, TopoNode, TopoTone } from '@/utils/topoLayout'

/**
 * 拓扑渲染（spec §5.2-8）：节点=圆角矩形+状态点+标签，边=直线；
 * 机器节点可点/可键盘激活，跳部署参数页由父组件决定（emit machine）。
 * 颜色一律走 --s2s-* 变量，本文件已进 hex-ban ratchet。
 */
const props = defineProps<{ layout: TopoLayout }>()
const emit = defineEmits<{ machine: [host: string] }>()
const { t } = useI18n()

const NODE_W = 128
const NODE_H = 34

const TONE_VAR: Record<TopoTone, string> = {
  ok: 'var(--s2s-color-success)',
  warn: 'var(--s2s-color-warning)',
  bad: 'var(--s2s-color-danger)',
  muted: 'var(--s2s-color-muted)'
}

const nodeById = (id: string): TopoNode | undefined =>
  props.layout.layers.flatMap((layer) => layer.nodes).find((node) => node.id === id)

const edgePoints = () =>
  props.layout.edges
    .map((edge) => {
      const from = nodeById(edge.from)
      const to = nodeById(edge.to)
      if (!from || !to) return null
      return { x1: from.x, y1: from.y + NODE_H / 2, x2: to.x, y2: to.y - NODE_H / 2, key: `${edge.from}->${edge.to}` }
    })
    .filter((p): p is NonNullable<typeof p> => p !== null)

function onMachine(node: TopoNode): void {
  if (node.id === 'machine:empty') return
  emit('machine', node.label)
}
</script>

<template>
  <svg
    class="topo"
    :viewBox="`0 0 ${props.layout.width} ${props.layout.height}`"
    role="img"
    :aria-label="t('overview.topology.title')"
  >
    <line
      v-for="edge in edgePoints()"
      :key="edge.key"
      :x1="edge.x1"
      :y1="edge.y1"
      :x2="edge.x2"
      :y2="edge.y2"
      class="topo__edge"
    />
    <g v-for="layer in props.layout.layers" :key="layer.key">
      <text :x="8" :y="layer.y - 14" class="topo__caption">{{ t(`overview.topology.${layer.key}Layer`) }}</text>
      <g
        v-for="node in layer.nodes"
        :key="node.id"
        :transform="`translate(${node.x - NODE_W / 2}, ${node.y - NODE_H / 2})`"
        :class="['topo__node', `is-${node.kind}`]"
        :tabindex="node.kind === 'machine' && node.id !== 'machine:empty' ? 0 : undefined"
        :role="node.kind === 'machine' && node.id !== 'machine:empty' ? 'button' : undefined"
        :aria-label="node.kind === 'machine' && node.id !== 'machine:empty' ? node.label : undefined"
        @click="node.kind === 'machine' && onMachine(node)"
        @keydown.enter="node.kind === 'machine' && onMachine(node)"
      >
        <rect :width="NODE_W" :height="NODE_H" rx="8" class="topo__box" :stroke="TONE_VAR[node.tone]" />
        <circle v-if="node.id !== `${node.kind}:empty`" cx="14" cy="17" r="4" :fill="TONE_VAR[node.tone]" />
        <text x="26" y="22" class="topo__label">{{ node.label || '—' }}</text>
      </g>
    </g>
  </svg>
</template>

<style scoped lang="less">
.topo {
  width: 100%;

  &__edge {
    stroke: var(--s2s-color-border);
    stroke-width: 1.5;
  }

  &__caption {
    fill: var(--s2s-color-muted);
    font-family: var(--s2s-font-mono);
    font-size: 11px;
  }

  &__box {
    fill: var(--s2s-color-surface-2);
    stroke-width: 1.5;
  }

  &__label {
    fill: var(--s2s-color-text);
    font-family: var(--s2s-font-mono);
    font-size: 12px;
  }

  &__node.is-machine {
    cursor: pointer;

    &:hover .topo__box {
      stroke: var(--s2s-color-accent);
    }

    &:focus-visible .topo__box {
      stroke: var(--s2s-color-accent);
      stroke-width: 2.5;
    }
  }
}
</style>