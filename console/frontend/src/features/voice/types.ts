/** The nine painted states of the orb page (demo/main.js:174-197, same names). */
export type VoiceState =
  | 'idle'
  | 'connecting'
  | 'queued'
  | 'your-turn'
  | 'listening'
  | 'user-speaking'
  | 'processing'
  | 'ai-speaking'
  | 'error'

/** The four states that mean “a call is up”. */
export const LIVE_STATES: ReadonlySet<VoiceState> = new Set([
  'listening',
  'user-speaking',
  'processing',
  'ai-speaking'
])

export interface TranscriptAudio {
  /** `URL.createObjectURL(pcm16ToWavBlob(...))`；条目被替换时 `revokeObjectURL`。 */
  url: string
  durationMs: number
  /** 录音器已经剪掉了这段语音的开头（超过 `maxBufferMs`）。 */
  truncated: boolean
}

export interface TranscriptTool {
  name: string
  input: string
  output: string
  /** `camera_snapshot` 的 data URL；无图时是 `''`，模板据此决定要不要渲染 `<img>`。 */
  image: string
}

export interface TranscriptEntry {
  /** `u:<itemId>` / `a:<responseId>` / `t:<callId>` — stable across partial and final updates. */
  key: string
  role: 'user' | 'assistant' | 'tool'
  text: string
  partial: boolean
  /** 只有 WebSocket 传输下的用户条目带原音（demo 的 `user-audio` 事件，§3.2.2）。 */
  audio?: TranscriptAudio
  /** 只有 tool 条目带调用信息与图片（`_appendHistTool` / `_appendHistImage`）。 */
  tool?: TranscriptTool
  /**
   * 助手条目的 `Server timings`（服务端 `speech_to_speech.turn_latency`，§3.9.4）。
   * 取不到时是 `undefined`——条目只显示文本，不显示一排 0。
   */
  latency?: TurnLatency
}

/** 舞台上右上角一闪而过的气泡（demo 的 `#bubble-stack`）。 */
export interface Bubble {
  id: number
  role: 'user' | 'tool' | 'assistant'
  text: string
}

/** The metering fields the server bolts onto every grant (demo/server.py:653-660). */
export interface SessionGrant {
  sessionId: string
  connectUrl: string
  websocketUrl?: string
  sessionToken?: string
  pendingTimeoutS?: number
  tier: string
  limited: boolean
  remainingSec: number | null
  heartbeatSec: number | null
}

export interface QueueTicket {
  queueId: string
  position: number
  pollIntervalS: number
}

/** `/api/me` — shape is owned by Task 18's router, not by this file. */
export interface MeResponse {
  enabled: boolean
  auth?: boolean
  loggedIn?: boolean
  tier?: string
  username?: string
  avatar?: string
  remainingSec?: number | null
  limitSec?: number | null
  loginUrl?: string | null
  logoutUrl?: string | null
}

/**
 * 浏览器侧可写的会话设置。字段与 `demo/main.js` 写进 localStorage 的键一一对应；
 * 唯一的例外是 `searchKey`：**它不进任何 storage**（Global Constraints B5）。
 */
export interface VoiceSettings {
  voice: string
  instructions: string
  noiseGateDb: number
  playbackBufferMs: number
  localVad: boolean
  transport: 'ws' | 'webrtc'
  tools: { web: boolean; camera: boolean }
  audioInputId: string
  audioOutputId: string
}

/** 部署实际连的那一个 pipeline（`PIPELINE_BASE_URL` / `PIPELINE_CONTAINER`）。 */
export interface PipelineInfo {
  baseUrl: string
  container: string
}

/** `/api/config` — Task 17. `lb` is a boolean; the LB address never comes down. */
export interface VoiceConfig {
  search: boolean
  lb: boolean
  allowDirect: boolean
  s2sUrl: string
  rtc: boolean
  iceServers: RTCIceServer[]
  startupGreeting: string
  auth: boolean
  pipeline: PipelineInfo
}

/** `speech_to_speech.turn_latency` v1/v2 (demo/turn-latency.js:2-18). */
export interface TurnLatency {
  version: number
  turn_id: string | null
  source?: 'speech' | 'client' | 'tool' | null
  turn_revision: number
  response_key: string
  status: string
  stt_s: number | null
  llm_s: number | null
  tts_ttfa_s: number | null
  e2e_s: number | null
  vad_decision_s?: number | null
  smart_wait_s?: number | null
  smart_status?: 'complete' | 'incomplete' | 'failed' | 'disabled' | null
  hold_s?: number | null
}

export interface ToolDef {
  type: 'function'
  name: string
  description: string
  parameters: Record<string, unknown>
}

export interface ToolCall {
  name: string
  arguments: string
  callId: string
}

export interface ToolResult {
  output: string
  /** Base64 data URL; the client turns it into an `addImage` turn. */
  image?: string
}
