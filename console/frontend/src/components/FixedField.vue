<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import ExposureTag from '@/components/ExposureTag.vue'
import type { CatalogEntry } from '@/types/catalog'

const props = defineProps<{ entry: CatalogEntry }>()
const { t } = useI18n()

/** 原因只由 `stage` 与 `type` 决定，不靠猜：合计 17 + 7 + 18 + 18 = 60。 */
const reason = computed(() => {
  if (props.entry.type === 'fixed') return t('deploy.fixed.sourceConstant')
  if (props.entry.stage === 'deploy') return t('deploy.fixed.platformMaintained')
  if (props.entry.stage === 'env') return t('deploy.fixed.recreateContainer')
  if (props.entry.stage === 'client') return t('deploy.fixed.clientSide')
  return t('deploy.fixed.notConfigurable')
})
</script>

<template>
  <div class="fixed-field">
    <div class="fixed-field__head">
      <span class="fixed-field__name">{{ entry.name }}</span>
      <ExposureTag :exposure="entry.exposure" />
      <a-tag color="default">{{ t('deploy.fixedTag') }}</a-tag>
      <span class="fixed-field__reason">{{ reason }}</span>
    </div>
    <p class="fixed-field__ref">{{ entry.source_ref }}</p>
  </div>
</template>

<style scoped lang="less">
.fixed-field {
  border-bottom: 1px solid #1e2742;
  padding: 10px 0;

  &__head {
    align-items: center;
    display: flex;
    gap: 8px;
  }

  &__name {
    color: #9aa3b8;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
  }

  &__reason {
    color: #8b93a7;
    font-size: 12px;
  }

  &__ref {
    color: #6f7891;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    margin: 4px 0 0;
    word-break: break-all;
  }
}
</style>
