import type { TranscriptEntry } from '../types'

interface Cell {
  /** Finalised text from `.done` events (assistant) — never overwritten downward. */
  full: string
  /** Delta accumulator. */
  partial: string
  /** Authoritative input transcript, once the server sends one. */
  snapshot: string
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

  reset(): void {
    this.entries.length = 0
    this.cells.clear()
    this.index.clear()
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
