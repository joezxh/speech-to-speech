<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

import type { TranscriptEntry } from '../types'
import AudioReplay from './AudioReplay.vue'
import TurnTimings from './TurnTimings.vue'

const props = defineProps<{ entries: TranscriptEntry[] }>()
const emit = defineEmits<{ (e: 'replay', playing: boolean): void }>()
const list = ref<HTMLElement | null>(null)
/** 同时只允许一条条目在响；`AudioReplay` 听这个值自己暂停。 */
const playingKey = ref('')

const ROLE_LABEL: Record<TranscriptEntry['role'], string> = {
  user: 'You',
  tool: 'Tool',
  assistant: 'Assistant'
}

watch(
  () => props.entries.map((entry) => `${entry.key}:${entry.text.length}:${entry.partial}`).join('|'),
  async () => {
    await nextTick()
    // Only stick to the bottom while the user is already there: scrolling a
    // reader back down after they scrolled up to read is hostile.
    const el = list.value
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 120) el.scrollTop = el.scrollHeight
  }
)

function onAudioPlay(key: string): void {
  playingKey.value = key
  // 播放原音时必须静音麦克风，否则录音会被重新送进 pipeline（回声）；
  // 旧页就是靠这一个回调做的（demo/main.js:372-406）。
  emit('replay', true)
}

function onAudioStop(): void {
  playingKey.value = ''
  emit('replay', false)
}
</script>

<template>
  <ol ref="list" class="transcript" aria-live="polite">
    <li
      v-for="entry in props.entries"
      :key="entry.key"
      class="transcript__item"
      :class="[`transcript__item--${entry.role}`, { 'is-partial': entry.partial }]"
    >
      <span class="transcript__role">{{ ROLE_LABEL[entry.role] }}</span>
      <span class="transcript__text">{{ entry.text }}</span>

      <!-- 用户条目：只有带音频的条目才有播放器（demo 也只在 websocket 分支产生原音）。 -->
      <AudioReplay
        v-if="entry.audio"
        :url="entry.audio.url"
        :truncated="entry.audio.truncated"
        :active="playingKey === entry.key"
        @play="onAudioPlay(entry.key)"
        @stop="onAudioStop"
      />

      <!-- tool 条目：Input / Output 可展开 + Snapshot 缩略图。 -->
      <details v-if="entry.tool" class="transcript__tool">
        <summary class="transcript__tool-name">{{ entry.tool.name }}</summary>
        <p class="transcript__tool-label">Input</p>
        <pre class="transcript__tool-json">{{ entry.tool.input }}</pre>
        <p class="transcript__tool-label">Output</p>
        <pre class="transcript__tool-json">{{ entry.tool.output }}</pre>
        <template v-if="entry.tool.image">
          <p class="transcript__tool-label">Snapshot</p>
          <a :href="entry.tool.image" target="_blank" rel="noopener">
            <img class="transcript__tool-image" :src="entry.tool.image" alt="Camera snapshot" />
          </a>
        </template>
      </details>

      <!--
        助手条目：服务端测的七行计时（`_appendTimings`）。`latency` 缺失时整块不渲染；
        同一条目后来收到更完整的 payload 时由 `TurnTimings` 内部整体替换（`chat.js:674` 的 remove-then-append）。
      -->
      <TurnTimings v-if="entry.latency" :latency="entry.latency" />
    </li>
  </ol>
</template>
