<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { waveBars } from './waveBars'

/**
 * 片段条 pill（原型 `.clip`）：波形条 + 时长。纯渲染：播放/失败状态由调用方管理。
 */
const props = defineProps<{
  seed: string
  durationMs: number
  disabled?: boolean
  playing?: boolean
}>()

const emit = defineEmits<{ (e: 'play'): void }>()

const { t } = useI18n()

const bars = computed(() => waveBars(props.seed, 12))

/** m:ss（原型 fmtClock 语义）。 */
const dur = computed(() => {
  const total = Math.max(0, Math.round(props.durationMs / 1000))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
})
</script>

<template>
  <button
    type="button"
    class="clip"
    :disabled="props.disabled"
    :data-playing="props.playing ? 'true' : undefined"
    :title="props.disabled ? t('sessions.card.noClip') : t('sessions.card.voice')"
    @click="emit('play')"
  >
    <span class="clip__bars"><i v-for="(h, i) in bars" :key="i" :style="{ height: `${h}px` }" /></span>
    <span class="clip__dur">{{ dur }}</span>
  </button>
</template>

<style scoped lang="less">
.clip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 3px 9px 3px 8px;
  border-radius: 999px;
  border: 1px solid var(--voice-border);
  background: rgba(139, 125, 255, 0.12);
  color: var(--voice-dim);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
  &:hover:not(:disabled) {
    border-color: var(--voice-accent);
    color: var(--voice-text);
  }
  &:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
  &[data-playing='true'] {
    border-color: var(--voice-accent);
    color: var(--voice-accent);
  }
  &__bars {
    display: flex;
    align-items: flex-end;
    gap: 1.5px;
    height: 11px;
    i {
      width: 2px;
      background: var(--voice-accent);
      opacity: 0.8;
      border-radius: 1px;
    }
  }
  &__dur {
    font-family: var(--mono);
    font-size: 10.5px;
  }
}
</style>
