<script setup lang="ts">
import type { Bubble } from '../types'

/**
 * 舞台上的一闪而过气泡——`demo/ui/chat.js` 的 `_buildMessageEl` / `_spawnBubble` /
 * `_spawnVoiceBubble` 三种形态。停留与清理时机全在 `useBubbles` 里，
 * 这里只负责把状态画出来：淡入淡出交给 `TransitionGroup`，
 * 等价于 demo 手写的 `.in` / `.out` 两类。
 */
const props = defineProps<{ items: Bubble[] }>()

const ROLE_LABEL: Record<Bubble['role'], string> = {
  user: 'You',
  assistant: 'Assistant',
  tool: 'Tool'
}

/** 语音占位气泡的两个状态词，逐字取自 demo 的 `_setVoiceBubbleState`。 */
const VOICE_STATE_LABEL: Record<'listening' | 'sending', string> = {
  listening: 'Listening…',
  sending: 'Sending voice…'
}

/** 扳手机械图形：与 demo 的 `WRENCH_PATH` 同一条 path，工具气泡专用。 */
const WRENCH_PATH =
  'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z'
</script>

<template>
  <div class="v-bubbles" aria-live="polite" aria-atomic="false">
    <TransitionGroup name="v-bubble">
      <div
        v-for="item in props.items"
        :key="item.id"
        class="v-bubble"
        :class="[
          `v-bubble--${item.role}`,
          {
            'is-voice': item.voice,
            'is-listening': item.voiceState === 'listening',
            'is-sending': item.voiceState === 'sending'
          }
        ]"
        :role="item.voice ? 'status' : undefined"
      >
        <!-- 工具气泡：没有角色行，只有扳手与调用名（demo 的 `.bubble.tool`）。 -->
        <template v-if="item.role === 'tool'">
          <svg
            class="v-bubble__tool-icon"
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
          <span class="v-bubble__tool-text">{{ item.text }}</span>
        </template>

        <template v-else>
          <div class="v-bubble__role">{{ ROLE_LABEL[item.role] }}</div>
          <!-- 转写为空时整行隐藏（demo 的 `.bubble-body[hidden]`），占位状态除外。 -->
          <div v-show="item.text || item.voice" class="v-bubble__body">
            <template v-if="item.voice">
              <span class="v-bubble__wave" aria-hidden="true"><i /><i /><i /><i /><i /></span>
              <span class="v-bubble__state">{{ item.voiceState ? VOICE_STATE_LABEL[item.voiceState] : '' }}</span>
            </template>
            <template v-else>{{ item.text }}</template>
          </div>
        </template>
      </div>
    </TransitionGroup>
  </div>
</template>
