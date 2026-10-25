import type { TurnLatency } from './types'

/** Step 5 的实现；这里 re-export 的目的只是让组件只从一个模块取数。 */
export { readTurnLatency } from './transport/turn-latency'

export interface TimingRow {
  label: string
  value: string
}

/** `chat.js:637`：`null` 一律写 `Unavailable`，而不是 `0.00 s`。 */
const UNAVAILABLE = 'Unavailable'

export function formatSeconds(seconds: number | null | undefined): string {
  return typeof seconds === 'number' && Number.isFinite(seconds) ? `${seconds.toFixed(2)} s` : UNAVAILABLE
}

/** `chat.js:643-645`：e2e 没测到就只剩两个词。 */
export function timingSummary(turn: TurnLatency): string {
  if (turn.e2e_s == null) return 'Server timings'
  return `Server timings · ${turn.version === 2 ? 'E2E' : 'First audio'} ${formatSeconds(turn.e2e_s)}`
}

const STATUS_LABELS: Record<string, string> = {
  completed: 'Completed',
  cancelled: 'Interrupted',
  failed: 'Failed',
  incomplete: 'Incomplete'
}

/** 服务端枚举 → 旧页面画的四个词（`chat.js:649`），不是原枚举值。 */
export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? ''
}

/**
 * 七行、顺序与文案与 `chat.js:653-661` 完全一致。
 * `Smart Turn decision` 的取值是字符串（`disabled` / `complete` …），不是秒数。
 */
export function timingRows(turn: TurnLatency): TimingRow[] {
  return [
    { label: turn.version === 2 ? 'E2E time' : 'VAD handoff to first audio', value: formatSeconds(turn.e2e_s) },
    { label: 'VAD end decision', value: formatSeconds(turn.vad_decision_s) },
    { label: 'Smart Turn decision', value: turn.smart_status ?? UNAVAILABLE },
    { label: 'Transcription', value: formatSeconds(turn.stt_s) },
    { label: 'Response generation', value: formatSeconds(turn.llm_s) },
    { label: 'Voice synthesis to first audio', value: formatSeconds(turn.tts_ttfa_s) },
    {
      label: 'Hold time before response',
      value: formatSeconds(turn.version === 2 ? turn.hold_s : turn.smart_wait_s)
    }
  ]
}

/** `chat.js:671-673` 逐字：两句话说的是两个不同口径，不能互相代替。 */
export function timingNote(turn: TurnLatency): string {
  return turn.version === 2
    ? 'E2E: estimated speech end to first generated audio, excluding browser playback. Stages overlap and do not add up.'
    : 'First audio: VAD handoff to generated audio, excluding browser playback. Stages overlap and do not add up.'
}
