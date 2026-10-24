<script setup lang="ts">
import { computed } from 'vue'

import type { CatalogEntry } from '@/types/catalog'

/** catalog `effect=both` 但实际只有启动生效的三条：`audio.output.voice` 只是协议回显（§2.4）。 */
const STARTUP_ONLY = new Set(['qwen3_tts_speaker', 'kokoro_voice', 'openai_tts_voice'])

const props = defineProps<{ entry: CatalogEntry }>()

const badge = computed(() => {
  if (props.entry.effect === 'hot') return { text: '热更新', color: 'blue' }
  if (props.entry.effect === 'both') {
    return STARTUP_ONLY.has(props.entry.name)
      ? { text: '启动', color: 'default' }
      : { text: '启动 + 热更', color: 'purple' }
  }
  return { text: '启动', color: 'default' }
})

/** 只给被降级的那三条用小字提示，避免让读者以为平台擅自改了 catalog。 */
const downgraded = computed(
  () => props.entry.effect === 'both' && STARTUP_ONLY.has(props.entry.name)
)
</script>

<template>
  <span class="effect-badge">
    <a-tag :color="badge.color">{{ badge.text }}</a-tag>
    <small v-if="downgraded" title="catalog: both；audio.output.voice 只是协议回显">catalog: both</small>
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
