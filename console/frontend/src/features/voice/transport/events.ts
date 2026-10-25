import type { TranscriptEntry, TranscriptTool } from '../types'

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

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/**
 * Server event stream → the transcript list. Pure: no DOM, no SDK, no timers,
 * so `demo/tests/*.test.mjs` behaviour can be asserted directly.
 */
export class TranscriptReducer {
  readonly entries: TranscriptEntry[] = []

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
    const entry: TranscriptEntry = { key, role, text: value, partial }
    if (at === undefined) {
      this.index.set(key, this.entries.length)
      this.entries.push(entry)
    } else {
      this.entries[at] = entry
    }
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
