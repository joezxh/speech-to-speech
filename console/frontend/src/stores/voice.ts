import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { TranscriptReducer } from '@/features/voice/transport/events'
import type { ToolCallRecord, ToolResultRecord, TranscriptDetail } from '@/features/voice/transport/events'
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
import type { SentAudio } from '@/features/voice/audio/sent-audio'

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
  /**
   * 会话抽屉的开合 + 未读徽标。这两个必须住在 store 而不是页面本地：徽标画在
   * `ConsoleLayout` 的顶栏，抽屉开在 `VoiceView`，而 demo 的规则是「开着就不亮、
   * 点开即清」（`chat.js:116-122` `_markUnread` / `chat.js:93-98` `_openPanel`），
   * 两边读到同一份 `_panelOpen` 才可能咬合。
   */
  const historyOpen = ref(false)
  const unread = ref(false)

  const reducer = new TranscriptReducer()
  const live = computed(() => LIVE_STATES.has(state.value))

  /**
   * `item_id` → object URL。条目本身会被替换而不是就地修改，所以 URL 的生杀必须记在这
   * 一层，否则一个通话里切过的每一段 WAV 都会漏在内存里（demo 的 `_audioUrls`）。
   */
  const audioUrls = new Map<string, string>()

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
    markUnread()
  }

  /** 工具调用的两段式：先占位，再接结果（`TranscriptReducer.toolCall/toolResult`）。 */
  function applyToolCall(call: ToolCallRecord): void {
    if (!reducer.toolCall(call)) return
    entries.value = [...reducer.entries]
    markUnread()
  }

  function applyToolResult(result: ToolResultRecord): void {
    if (!reducer.toolResult(result)) return
    entries.value = [...reducer.entries]
    markUnread()
  }

  /**
   * 把刚发出去的那段原音挂到它自己的用户条目上（demo 的 `chat.onUserAudio`）。
   * 同一个 `item_id` 的投机续接会交出拼接后的整段 WAV：播放器只有一个，只是逐次变长，
   * 所以旧 URL 先 revoke 再换新的。
   */
  function applyUserAudio(recording: SentAudio): void {
    if (!recording.itemId) return
    const url = URL.createObjectURL(recording.blob)
    const previous = audioUrls.get(recording.itemId)
    if (previous) URL.revokeObjectURL(previous)
    audioUrls.set(recording.itemId, url)
    if (!reducer.userAudio({ itemId: recording.itemId, url, durationMs: recording.durationMs, truncated: recording.truncated })) return
    entries.value = [...reducer.entries]
    markUnread()
  }

  /**
   * 气泡层订阅每一次转写更新（demo 客户端的 `transcript` 事件）。传 `null` 退订：
   * 页面卸载后 reducer 不该再握着一个已经销毁的组件回调。
   */
  function subscribeTranscript(handler: ((detail: TranscriptDetail) => void) | null): void {
    reducer.onTranscript = handler
  }

  /**
   * 被用户插话打断的那一句（demo `chat.js:615-627`：`response.done` 的 `cancelled`）。
   * 必须在 `attachLatency` 之前调：补建的那一行才是本轮计时的归属，否则数字会挂到上一句。
   */
  function markInterrupted(responseId: string, transcript: string): void {
    if (!reducer.interrupt(responseId, transcript)) return
    entries.value = [...reducer.entries]
    markUnread()
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
    markUnread()
  }

  /**
   * 抽屉关着时，任何新落地的内容都把徽标点亮；开着时只算「已经看见了」，
   * 交给列表自己滚到底（demo 的 `_markUnread` 在 `_panelOpen` 时直接返回）。
   */
  function markUnread(): void {
    if (historyOpen.value) return
    unread.value = true
  }

  function openHistory(): void {
    historyOpen.value = true
    unread.value = false
  }

  function closeHistory(): void {
    historyOpen.value = false
  }

  /** 顶栏的会话按钮是开合切换（demo chat.js:83），不是只会打开。 */
  function toggleHistory(): void {
    if (historyOpen.value) closeHistory()
    else openHistory()
  }

  function resetTranscript(): void {
    for (const url of audioUrls.values()) URL.revokeObjectURL(url)
    audioUrls.clear()
    reducer.reset()
    entries.value = []
    latency.value = null
    // 新一通电话从「没有未读」开始（demo 的 `clear()` 一并摘掉徽标）。
    unread.value = false
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
    historyOpen,
    unread,
    setState,
    applyEvent,
    applyToolCall,
    applyToolResult,
    applyUserAudio,
    subscribeTranscript,
    markInterrupted,
    attachLatency,
    openHistory,
    closeHistory,
    toggleHistory,
    resetTranscript,
    loadSettings,
    saveSettings
  }
})
