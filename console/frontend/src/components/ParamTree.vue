<script setup lang="ts">
import { computed } from 'vue'

import type { CatalogEntry } from '@/types/catalog'
import { groupByStage } from '@/utils/catalog-view'

const props = defineProps<{ entries: CatalogEntry[]; selected: string }>()
const emit = defineEmits<{ select: [key: string] }>()

const groups = computed(() => groupByStage(props.entries))
const selectedKeys = computed(() => [props.selected])
</script>

<template>
  <a-menu mode="inline" theme="dark" :selected-keys="selectedKeys" class="param-tree">
    <a-menu-item v-for="group in groups" :key="group.key" @click="emit('select', group.key)">
      <span class="param-tree__stage">{{ group.stage }}</span>
      <span class="param-tree__backend">· {{ group.backend ?? '通用' }}</span>
      <a-tag v-if="group.readOnly" class="param-tree__ro">只读</a-tag>
      <a-tag class="param-tree__count">{{ group.items.length }}</a-tag>
    </a-menu-item>
  </a-menu>
  <!-- 分母来自 catalog 本身，不是当前分组的条数（§6.1 / 预览页 `catalog__count`）。 -->
  <p class="param-tree__total">{{ groups.length }} 组 · 共 {{ entries.length }} 条</p>
</template>

<style scoped lang="less">
.param-tree {
  background: transparent;
  max-height: calc(100vh - 300px);
  overflow-y: auto;

  &__stage {
    font-family: 'JetBrains Mono', monospace;
  }

  &__backend {
    color: #8b93a7;
    font-size: 12px;
    margin-left: 2px;
  }

  &__ro {
    margin-left: 4px;
    transform: scale(0.85);
  }

  &__count {
    float: right;
    margin-top: 4px;
  }

  &__total {
    color: #6f7891;
    font-size: 12px;
    margin: 8px 0 0;
    padding: 0 12px;
  }
}
</style>
