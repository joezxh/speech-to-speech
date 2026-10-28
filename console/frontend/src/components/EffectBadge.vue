<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { CatalogEntry } from '@/types/catalog'

/** catalog `effect=both` 但实际只有启动生效的三条：`audio.output.voice` 只是协议回显（§2.4）。 */
const STARTUP_ONLY = new Set(['qwen3_tts_speaker', 'kokoro_voice', 'openai_tts_voice'])

const props = defineProps<{ entry: CatalogEntry }>()
const { t } = useI18n()

const badge = computed(() => {
  if (props.entry.effect === 'hot') return { text: t('deploy.effect.hot'), color: 'blue' }
  if (props.entry.effect === 'both') {
    return STARTUP_ONLY.has(props.entry.name)
      ? { text: t('deploy.effect.startup'), color: 'default' }
      : { text: t('deploy.effect.startupHot'), color: 'purple' }
  }
  return { text: t('deploy.effect.startup'), color: 'default' }
})

/** 只给被降级的那三条用小字提示，避免让读者以为平台擅自改了 catalog。 */
const downgraded = computed(
  () => props.entry.effect === 'both' && STARTUP_ONLY.has(props.entry.name)
)
</script>

<template>
  <span class="effect-badge">
    <a-tag :color="badge.color">{{ badge.text }}</a-tag>
    <small v-if="downgraded" :title="t('deploy.effectDowngradeTitle')">catalog: both</small>
  </span>
</template>

<style scoped lang="less">
.effect-badge {
  align-items: center;
  display: inline-flex;
  gap: 4px;

  small {
    color: #6f7891;
    font-size: 11px;
  }
}
</style>
