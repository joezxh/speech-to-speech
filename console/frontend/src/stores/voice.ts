import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { TranscriptReducer } from '@/features/voice/transport/events'
import type { ToolCallRecord, ToolResultRecord } from '@/features/voice/transport/events'
import { LIVE_STATES } from '@/features/voice/types'
import type {
  MeResponse,
  QueueTicket,
  SessionGrant,
  TranscriptEntry,
  TurnLatency,
  VoiceConfig,
  VoiceSettings,
  VoiceState
} from '@/features/voice/types'

/**
 * 唯一持久化的东西：设置。demo/main.js 也把同一组值写进 localStorage
 * （voice / instructions / noiseGate / playbackBufferMs / localVad /
 * transport / audioInputId / audioOutputId / tools），但不写转写。
 * 刷新 = 会话结束，这一点与 demo 完全一致。
 */
export const SETTINGS_KEY = 's2s.voice.settings'

export const DEFAULT_SETTINGS: VoiceSettings = {
  voice: 'Aiden',
  instructions: 'You are a friendly voice assistant.',
  noiseGateDb: -50,
  playbackBufferMs: 0,
  localVad: true,
  transport: 'ws',
  tools: { web: true, camera: false },
  audioInputId: '',
  audioOutputId: ''
}

/** 客户端报的是 transport 状态；orb 只有九态，`connected` 画成 `listening`。 */
export type VoiceStatus = VoiceState | 'connected' | 'closed'

const PAINTED = new Set<VoiceState>([
  'idle',
  'connecting',
  'queued',
  'your-turn',
  'listening',
  'user-speaking',
  'processing',
  'ai-speaking',
  'error'
])

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    // Private mode throws on access; the page still has to work.
    return null
  }
}

/** 逐字段合并：旧版本存下的部分记录也能用，未知字段直接忽略。 */
export function mergeSettings(saved: Partial<VoiceSettings> | null): VoiceSettings {
  const tools = { ...DEFAULT_SETTINGS.tools, ...(saved?.tools ?? {}) }
  return { ...DEFAULT_SETTINGS, ...(saved ?? {}), tools }
}

const EMPTY_CONFIG: VoiceConfig = {
  search: false,
  lb: false,
  allowDirect: true,
  s2sUrl: '',
  rtc: false,
  iceServers: [],
  startupGreeting: '',
  auth: false,
  pipeline: { baseUrl: '', container: '' }
}

export const useVoiceStore = defineStore('voice', () => {
  const state = ref<VoiceState>('idle')
  const entries = ref<TranscriptEntry[]>([])
  const grant = ref<SessionGrant | null>(null)
  const queue = ref<QueueTicket | null>(null)
  const me = ref<MeResponse>({ enabled: false })
  const config = ref<VoiceConfig>({ ...EMPTY_CONFIG })
  const latency = ref<TurnLatency | null>(null)
  const settings = ref<VoiceSettings>(mergeSettings(null))

  const reducer = new TranscriptReducer()
  const live = computed(() => LIVE_STATES.has(state.value))

  function setState(next: VoiceStatus): void {
    // `closed` 不是一种画面：关闭后停在当前状态，由页面决定是否回到 `idle`。
    if (next === 'closed') return
    if (next === 'connected') {
      state.value = 'listening'
      return
    }
    // 未知状态直接忽略：写进 `state` 只会让 `OrbStage` 的 INDICATOR 查空。
    if (!PAINTED.has(next)) return
    state.value = next
  }

  function applyEvent(event: any): void {
    if (!reducer.apply(event)) return
    entries.value = [...reducer.entries]
  }

  /** 工具调用的两段式：先占位，再接结果（`TranscriptReducer.toolCall/toolResult`）。 */
  function applyToolCall(call: ToolCallRecord): void {
    if (!reducer.toolCall(call)) return
    entries.value = [...reducer.entries]
  }

  function applyToolResult(result: ToolResultRecord): void {
    if (!reducer.toolResult(result)) return
    entries.value = [...reducer.entries]
  }

  /**
   * `Server timings` 的归属（§3.9.4）：demo 把它挂在「最后一条助手条目」上
   * （`chat.js:637`：`hist ??= this._appendHistMsg("assistant", …)`），而不是存一份全局最新值。
   * 找不到助手条目（转写还没到）时只丢掉这块数字，不造空节点——宁可少一条，也不挂错人。
   */
  function attachLatency(turn: TurnLatency | null): void {
    latency.value = turn
    if (!turn) return
    let index = -1
    for (let i = entries.value.length - 1; i >= 0; i -= 1) {
      if (entries.value[i].role === 'assistant') {
        index = i
        break
      }
    }
    if (index < 0) return
    entries.value = entries.value.map((entry, i) => (i === index ? { ...entry, latency: turn } : entry))
  }

  function resetTranscript(): void {
    reducer.reset()
    entries.value = []
    latency.value = null
  }

  function loadSettings(): void {
    const raw = storage()?.getItem(SETTINGS_KEY)
    if (!raw) {
      settings.value = mergeSettings(null)
      return
    }
    try {
      settings.value = mergeSettings(JSON.parse(raw) as Partial<VoiceSettings>)
    } catch {
      // 坏记录当成没存过：一个 JSON 解析失败不该让整页挂不上。
      settings.value = mergeSettings(null)
    }
  }

  function saveSettings(next: VoiceSettings = settings.value): void {
    settings.value = mergeSettings(next)
    storage()?.setItem(SETTINGS_KEY, JSON.stringify(settings.value))
  }

  return {
    state,
    entries,
    grant,
    queue,
    me,
    config,
    latency,
    settings,
    live,
    setState,
    applyEvent,
    applyToolCall,
    applyToolResult,
    attachLatency,
    resetTranscript,
    loadSettings,
    saveSettings
  }
})
