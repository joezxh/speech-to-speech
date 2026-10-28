<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { CatalogEntry } from '@/types/catalog'
import type { VoiceBackend } from '@/types/voice-library'
import { groupByStage } from '@/utils/catalog-view'

const { t } = useI18n()

const props = defineProps<{
  entries: CatalogEntry[]
  selected: string
  /** `GET /voices/backends` 里 `catalogued:false` 的后端：可见、无控件（§3.11.1）。 */
  uncatalogued?: VoiceBackend[]
}>()
const emit = defineEmits<{ select: [key: string] }>()

const groups = computed(() => groupByStage(props.entries))
const selectedKeys = computed(() => [props.selected])
const extraBackends = computed(() => props.uncatalogued ?? [])
</script>

<template>
  <a-menu mode="inline" theme="dark" :selected-keys="selectedKeys" class="param-tree">
    <a-menu-item v-for="group in groups" :key="group.key" @click="emit('select', group.key)">
      <span class="param-tree__stage">{{ group.stage }}</span>
      <span class="param-tree__backend">· {{ group.backend ?? t('deploy.commonBackend') }}</span>
      <a-tag v-if="group.readOnly" class="param-tree__ro">{{ t('deploy.readOnlyTag') }}</a-tag>
      <a-tag class="param-tree__count">{{ group.items.length }}</a-tag>
    </a-menu-item>
  </a-menu>
  <!-- 分母来自 catalog 本身，不是当前分组的条数（§6.1 / 预览页 `catalog__count`）。 -->
  <p class="param-tree__total">{{ t('deploy.treeTotal', { groups: groups.length, entries: entries.length }) }}</p>

  <!-- B4 目录化后端：字段没进机器目录，所以只说“这里是空的”，不给输入控件。 -->
  <div v-if="extraBackends.length" class="param-tree__extra">
    <p class="param-tree__extra-title">{{ t('deploy.uncataloguedBackends', { count: extraBackends.length }) }}</p>
    <p v-for="item in extraBackends" :key="`${item.stage}::${item.backend}`" class="param-tree__extra-row">
      <span class="param-tree__extra-name">{{ item.stage }} · {{ item.backend }}</span>
      <span class="param-tree__extra-note">{{ item.notes }}</span>
    </p>
  </div>
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

  &__extra {
    border-top: 1px dashed #1e2742;
    margin-top: 10px;
    padding: 8px 12px 0;
  }

  &__extra-title {
    color: #6f7891;
    font-size: 12px;
    margin: 0 0 6px;
  }

  &__extra-row {
    color: #8b93a7;
    display: flex;
    font-size: 12px;
    gap: 6px;
    margin: 0 0 4px;
  }

  &__extra-name {
    font-family: 'JetBrains Mono', monospace;
  }

  &__extra-note {
    color: #5b647c;
  }
}
</style>
