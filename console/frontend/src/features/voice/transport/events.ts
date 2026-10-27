import type { TranscriptAudio, TranscriptEntry, TranscriptTool } from '../types'

interface Cell {
  /** Finalised text from `.done` events (assistant) — never overwritten downward. */
  full: string
  /** Delta accumulator. */
  partial: string
  /** Authoritative input transcript, once the server sends one. */
  snapshot: string
}

/** 工具调用的两层：`call` 先到（条目占位），`result` 后到（补 Output / Snapshot）。 */
export interface ToolCallRecord {
  name: string
  arguments: string
  callId: string
}

export interface ToolResultRecord extends ToolCallRecord {
  output: string
  image?: string
  failed?: boolean
}

/**
 * 一次转写更新。气泡层要的就是这个，不是最终列表：demo 客户端为此专门发
 * `transcript` 事件（`s2s-realtime-client.js:619-635`）。reducer 是唯一的累加器，
 * 所以下游信号由它广播，调用方不必再算一遍增量。
 */
export interface TranscriptDetail {
  role: 'user' | 'assistant'
  text: string
  partial: boolean
  /** 用户轮次的身份；助手更新里是空串。 */
  itemId: string
  /** 助手回复的身份；用户更新里是空串。 */
  responseId: string
}

/** `SentAudioRecorder` 切出来的那一段，已经包成 WAV Blob 并由 store 换成了 object URL。 */
export interface UserAudioRecord {
  itemId: string
  url: string
  durationMs: number
  truncated: boolean
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/**
 * Server event stream → the transcript list. Pure: no DOM, no SDK, no timers,
 * so `demo/tests/*.test.mjs` behaviour can be asserted directly.
 */
export class TranscriptReducer {
  readonly entries: TranscriptEntry[] = []

  /**
   * 每次转写变化都通知一次（`write` 是唯一入口，所以不会漏也不会重）。
   * `null` = 没人在听：转写照常记账，抽屉不受影响。
   */
  onTranscript: ((detail: TranscriptDetail) => void) | null = null

  private readonly cells = new Map<string, Cell>()

  private readonly index = new Map<string, number>()

  /** `callId` 缺失时用它给 tool 条目编个稳定 key。 */
  private toolSeq = 0

  reset(): void {
    this.entries.length = 0
    this.cells.clear()
    this.index.clear()
    this.toolSeq = 0
  }

  private cell(key: string): Cell {
    let cell = this.cells.get(key)
    if (!cell) {
      cell = { full: '', partial: '', snapshot: '' }
      this.cells.set(key, cell)
    }
    return cell
  }

  private write(key: string, role: 'user' | 'assistant', value: string, partial: boolean): void {
    const at = this.index.get(key)
    const previous = at === undefined ? undefined : this.entries[at]
    // 已经挂上的原音与计时属于「这一行」，不属于「文本的某一次更新」：demo 的
    // `_updateHistMsg` 只改 `.hist-body`，播放器与 timings 节点都留在原地（chat.js:325-333）。
    const entry: TranscriptEntry = {
      key,
      role,
      text: value,
      partial,
      ...(previous?.audio ? { audio: previous.audio } : {}),
      ...(previous?.latency ? { latency: previous.latency } : {}),
      ...(previous?.interrupted ? { interrupted: previous.interrupted } : {})
    }
    if (at === undefined) {
      this.index.set(key, this.entries.length)
      this.entries.push(entry)
    } else {
      this.entries[at] = entry
    }
    // key 的前缀就是 `u:` / `a:`，去掉两个字即服务端给的 item_id / response_id。
    this.onTranscript?.({
      role,
      text: value,
      partial,
      itemId: role === 'user' ? key.slice(2) : '',
      responseId: role === 'assistant' ? key.slice(2) : ''
    })
  }

  /**
   * 原音挂到 `u:<itemId>` 那一行；行还不存在就先建一行空文本的用户条目
   * （demo 的 `_ensureUserHist`：关掉 STT 时，音频是这一轮存在过的唯一痕迹）。
   * 同一个 item 的投机续接会交出拼接后的整段 WAV，所以是替换而不是新增。
   */
  userAudio(recording: UserAudioRecord): boolean {
    const key = `u:${recording.itemId}`
    const audio: TranscriptAudio = {
      url: recording.url,
      durationMs: recording.durationMs,
      truncated: recording.truncated
    }
    const at = this.index.get(key)
    if (at === undefined) {
      this.index.set(key, this.entries.length)
      this.entries.push({ key, role: 'user', text: '', partial: false, audio })
      return true
    }
    this.entries[at] = { ...this.entries[at], audio }
    return true
  }

  /**
   * 被用户插话的回复（demo `chat.js:615-627`）：`response.done` 报 `cancelled`。
   * 已收到多少字就留多少，只补一枚 `Interrupted` 标记；转写事件完全没赶到时，
   * 用 `response.done` 自带的 `transcript` 补建一行（否则打断在历史里完全看不出来）。
   *
   * 这里不发 `onTranscript`：demo 只改历史行（`_markHistInterrupted`），舞台上那只气泡
   * 早就按自己的计时淡出，不能因为一个迟到的标记被重新点亮（不会调 `_bumpDismiss`）。
   */
  interrupt(responseId: string, transcript: string): boolean {
    if (!responseId) return false
    const key = `a:${responseId}`
    const at = this.index.get(key)
    if (at === undefined) {
      if (!transcript) return false
      this.cell(key).full = transcript
      this.index.set(key, this.entries.length)
      this.entries.push({ key, role: 'assistant', text: transcript, partial: false, interrupted: true })
      return true
    }
    const previous = this.entries[at]
    if (transcript) this.cell(key).full = transcript
    this.entries[at] = { ...previous, text: transcript || previous.text, partial: false, interrupted: true }
    return true
  }

  /** tool 条目的 key 与渲染都由调用 ID 决定，重复通知只替换不新增。 */
  private writeTool(key: string, tool: TranscriptTool, partial: boolean): void {
    const at = this.index.get(key)
    const entry: TranscriptEntry = { key, role: 'tool', text: tool.name, partial, tool }
    if (at === undefined) {
      this.index.set(key, this.entries.length)
      this.entries.push(entry)
    } else {
      this.entries[at] = entry
    }
  }

  /**
   * 模型要调工具时立即占位（半透明），拿到结果再补全——与 demo 里
   * `onToolCall` 冒气泡、`onToolResult` 落历史条目的两段式一致，只是这里
   * 让历史先出现一行“正在跑”，不会在慢工具上凭空静音。
   */
  toolCall(call: ToolCallRecord): boolean {
    const key = this.toolKey(call)
    this.writeTool(
      key,
      { name: call.name, input: prettyJson(call.arguments), output: '', image: '' },
      true
    )
    return true
  }

  /** 工具结果：同 key 覆盖，`partial` 归位，失败也写在 Output 里。 */
  toolResult(result: ToolResultRecord): boolean {
    const key = this.toolKey(result)
    this.writeTool(
      key,
      {
        name: result.name,
        input: prettyJson(result.arguments),
        output: result.output ?? '',
        image: result.image ?? ''
      },
      false
    )
    return true
  }

  private toolKey(call: ToolCallRecord): string {
    return `t:${call.callId || `local-${(this.toolSeq += 1)}`}`
  }

  private remove(key: string): void {
    const at = this.index.get(key)
    if (at === undefined) return
    // 挂着原音的行不能整行消失：转写失败或被剪空只是「没字」，不是「没说话」。
    // demo 的历史只增不减，空文本 + 播放器就是这一轮的记录（`_updateHistMsg` 的 `body.hidden`）。
    const previous = this.entries[at]
    const audio = previous.audio
    if (audio) {
      this.entries[at] = { key, role: previous.role, text: '', partial: false, audio }
      this.cells.delete(key)
      return
    }
    this.entries.splice(at, 1)
    this.index.clear()
    this.entries.forEach((entry, i) => this.index.set(entry.key, i))
  }

  /** @returns whether the rendered list changed. */
  apply(event: any): boolean {
    const type = typeof event?.type === 'string' ? event.type : ''
    switch (type) {
      case 'conversation.item.input_audio_transcription.delta': {
        const delta = text(event.delta)
        if (!delta) return false
        const key = `u:${text(event.item_id)}`
        const cell = this.cell(key)
        cell.partial += delta
        this.write(key, 'user', cell.snapshot || cell.partial, true)
        return true
      }
      case 'speech_to_speech.input_audio_transcription.snapshot': {
        const snapshot = text(event.transcript)
        if (!snapshot) return false
        const key = `u:${text(event.item_id)}`
        this.cell(key).snapshot = snapshot
        this.write(key, 'user', snapshot, true)
        return true
      }
      case 'conversation.item.input_audio_transcription.completed': {
        const key = `u:${text(event.item_id)}`
        const cell = this.cells.get(key)
        const hadPartial = Boolean(cell && (cell.partial || cell.snapshot))
        this.cells.delete(key)
        const final = text(event.transcript)
        if (final) {
          this.write(key, 'user', final, false)
          return true
        }
        if (hadPartial) {
          this.remove(key)
          return true
        }
        return false
      }
      case 'conversation.item.input_audio_transcription.failed': {
        const key = `u:${text(event.item_id)}`
        this.cells.delete(key)
        this.remove(key)
        return true
      }
      case 'response.audio_transcript.delta':
      case 'response.output_audio_transcript.delta': {
        const delta = text(event.delta)
        if (!delta) return false
        const key = `a:${text(event.response_id)}`
        const cell = this.cell(key)
        cell.partial += delta
        const shown = cell.full && cell.partial ? `${cell.full} ${cell.partial}` : cell.full || cell.partial
        this.write(key, 'assistant', shown, true)
        return true
      }
      case 'response.audio_transcript.done':
      case 'response.output_audio_transcript.done': {
        const key = `a:${text(event.response_id)}`
        const cell = this.cell(key)
        const segment = text(event.transcript) || cell.partial
        if (segment) cell.full = cell.full ? `${cell.full} ${segment}` : segment
        cell.partial = ''
        if (!cell.full) {
          this.remove(key)
          return true
        }
        this.write(key, 'assistant', cell.full, false)
        return true
      }
      default:
        // Audio frames, visemes, response.created, error … none of them are text.
        return false
    }
  }
}

/** `{"query":"x"}` → 多行 JSON；不是 JSON 就原样返回，绝不丢掉用户的参数。 */
function prettyJson(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}
