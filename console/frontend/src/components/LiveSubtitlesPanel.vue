<!-- 实时字幕面板：fetch 流式读取 SSE（EventSource 无法自定义 Authorization 头），
     渲染 LiveKit 房间转写事件；standalone console 部署收到 event: error 即停。 -->
<template>
  <div class="live-subtitles">
    <a-space class="live-subtitles__bar">
      <a-badge
        :status="connected ? 'processing' : 'error'"
        :text="connected ? t('callbacks.live.connected') : t('callbacks.live.disconnected')"
      />
      <a-button size="small" @click="togglePause">
        {{ paused ? t('callbacks.live.resume') : t('callbacks.live.pause') }}
      </a-button>
      <a-button size="small" danger @click="clear">{{ t('callbacks.live.clear') }}</a-button>
      <span class="live-subtitles__count">{{ lines.length }}</span>
    </a-space>
    <div ref="listEl" class="live-subtitles__list">
      <div v-for="(line, index) in lines" :key="index" class="live-subtitles__line">
        <span class="live-subtitles__meta">
          [{{ formatTime(line.timestamp) }}] {{ line.room }} / {{ line.identity }}
        </span>
        <span class="live-subtitles__text">{{ line.text }}</span>
      </div>
      <div v-if="!lines.length" class="live-subtitles__empty">{{ t('callbacks.live.empty') }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { readToken } from '@/utils/storage'

interface LiveLine {
  timestamp: number
  room: string
  identity: string
  text: string
  eventType: string
}

const { t } = useI18n()
const lines = ref<LiveLine[]>([])
const connected = ref(false)
const paused = ref(false)
const listEl = ref<HTMLElement | null>(null)
let controller: AbortController | null = null
const MAX_LINES = 500

// 与 `@/api/client` 的 baseURL（'/api/v1'，same-origin relative，D1）同一约定：
// 页面不感知上游地址，fetch 直接走同源相对路径。
const STREAM_URL = '/api/v1/live-transcripts/stream'

function formatTime(ts: number): string {
  if (!ts) return '--:--:--'
  return new Date(ts).toLocaleTimeString()
}

function pushLine(payload: Record<string, unknown>): void {
  if (paused.value) return
  lines.value.push({
    timestamp: Number(payload.timestamp ?? 0),
    room: String(payload.roomSid ?? ''),
    identity: String(payload.identity ?? ''),
    text: String(payload.text ?? ''),
    eventType: String(payload.eventType ?? '')
  })
  if (lines.value.length > MAX_LINES) {
    lines.value.splice(0, lines.value.length - MAX_LINES)
  }
  nextTick(() => listEl.value?.scrollTo({ top: listEl.value.scrollHeight }))
}

async function connect(): Promise<void> {
  controller = new AbortController()
  try {
    const response = await fetch(STREAM_URL, {
      headers: { Authorization: `Bearer ${readToken()}` },
      signal: controller.signal
    })
    if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)
    connected.value = true
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // SSE 以空行分帧；`event: error` 帧 = standalone console 部署（worker 不在本进程），
      // 置断开并停止，不做重试。`: keep-alive` 注释行两条前缀都不命中，天然忽略。
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''
      let stopped = false
      for (const frame of frames) {
        for (const row of frame.split('\n')) {
          if (row.startsWith('event: error')) {
            stopped = true
            break
          }
          if (row.startsWith('data: ')) {
            try {
              pushLine(JSON.parse(row.slice(6)) as Record<string, unknown>)
            } catch {
              // 坏帧直接丢弃，不影响后续事件。
            }
          }
        }
        if (stopped) break
      }
      if (stopped) return
    }
  } catch (caught) {
    // AbortError（组件卸载 / 页签切换）或网络中断：状态在 finally 统一回落。
    void caught
  } finally {
    connected.value = false
  }
}

function togglePause(): void {
  paused.value = !paused.value
}

function clear(): void {
  lines.value = []
}

onMounted(() => {
  void connect()
})

onBeforeUnmount(() => {
  controller?.abort()
})
</script>

<style scoped lang="less">
.live-subtitles {
  display: flex;
  flex-direction: column;

  &__bar {
    margin-bottom: 12px;
  }

  &__list {
    border: 1px solid var(--s2s-color-border);
    border-radius: 6px;
    height: 420px;
    overflow-y: auto;
    padding: 8px 12px;
  }

  &__line {
    line-height: 1.6;
    margin: 4px 0;
  }

  &__meta {
    color: var(--s2s-color-muted);
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    margin-right: 8px;
  }

  &__text {
    font-size: 14px;
  }

  &__empty {
    color: var(--s2s-color-muted);
    padding: 40px 0;
    text-align: center;
  }

  &__count {
    color: var(--s2s-color-muted);
    font-size: 12px;
  }
}
</style>
