<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { TranscriptEntry } from '@/features/voice/types'

/**
 * 对话图标下方的持久双侧转写——对齐原型 `#/conversation` 的 `.transcript`：
 * `.bubble.user` 右侧紫、`.bubble.assistant` 左侧灰、meta 居中提示（原型 282-286 行）。
 * 数据源 = voice store 的整通话 entries（save 用的同一份），不是瞬时气泡。
 */
const props = defineProps<{ entries: TranscriptEntry[] }>()

const { t } = useI18n()

/** 扳手图形与 BubbleStack 同一条 path（工具行沿用）。 */
const WRENCH_PATH =
  'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z'
</script>

<template>
  <div class="st" aria-live="polite">
    <div v-if="!props.entries.length" class="st__meta">{{ t('voiceStage.hint') }}</div>
    <template v-else>
      <div
        v-for="item in props.entries"
        :key="item.key"
        class="st__bubble"
        :class="`st__bubble--${item.role}`"
        :data-role="item.role"
        :data-partial="item.partial ? 'true' : undefined"
      >
        <span v-if="item.role === 'user'" class="st__who">{{ t('voiceStage.whoUser') }}</span>
        <span v-else-if="item.role === 'assistant'" class="st__who">{{ t('voiceStage.whoAssistant') }}</span>
        <svg
          v-if="item.role === 'tool'"
          class="st__tool-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path :d="WRENCH_PATH" />
        </svg>
        <span class="st__text">{{ item.text }}<i v-if="item.partial" class="st__caret" /></span>
      </div>
    </template>
  </div>
</template>

<style scoped lang="less">
.st {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  text-align: left;
  max-height: 300px;
  overflow-y: auto;
  padding: 0 4px;

  &__meta {
    align-self: center;
    font-size: 11.5px;
    color: var(--voice-faint);
    background: transparent;
    border: 0;
    padding: 4px 0;
  }
  &__bubble {
    max-width: 78%;
    padding: 9px 13px;
    border-radius: 14px;
    font-size: 13.5px;
    line-height: 1.55;
    display: flex;
    gap: 8px;
    align-items: baseline;
    border: 1px solid var(--voice-border);
    color: var(--voice-text);

    &[data-role='user'] {
      align-self: flex-end;
      background: rgba(139, 125, 255, 0.22);
      border-color: rgba(139, 125, 255, 0.35);
    }
    &[data-role='assistant'],
    &[data-role='tool'] {
      align-self: flex-start;
      background: var(--voice-surface-2);
    }
  }
  &__who {
    flex: 0 0 auto;
    font-size: 10.5px;
    color: var(--voice-faint);
  }
  &__text {
    flex: 1;
    min-width: 0;
    word-break: break-word;
  }
  &__caret {
    display: inline-block;
    width: 1px;
    height: 0.9em;
    background: currentColor;
    margin-left: 2px;
    animation: st-caret 0.9s step-end infinite;
  }
  &__tool-icon {
    flex: 0 0 14px;
    width: 14px;
    height: 14px;
    align-self: center;
  }
}

@keyframes st-caret {
  50% {
    opacity: 0;
  }
}
</style>
