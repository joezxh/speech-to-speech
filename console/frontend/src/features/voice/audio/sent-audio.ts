/** pipeline 上行采样率，不是浏览器的 48kHz。 */
export const USER_AUDIO_SAMPLE_RATE = 24000
const BYTES_PER_SAMPLE = 2
const DEFAULT_PREROLL_MS = 5000
const DEFAULT_MAX_BUFFER_MS = 120_000

export interface SentAudio {
  blob: Blob
  durationMs: number
  /** 开头被剪掉了：条目要显示 `· beginning unavailable`。 */
  truncated: boolean
}

export function pcm16ToWavBlob(pcm: Int16Array, sampleRate = USER_AUDIO_SAMPLE_RATE): Blob {
  const samples = new Int16Array(pcm) // 自带 buffer，避免 subarray 共享出 44 字节以外的脏数据
  const header = new ArrayBuffer(44)
  const view = new DataView(header)
  const ascii = (offset: number, text: string): void => {
    for (let index = 0; index < text.length; index += 1) view.setUint8(offset + index, text.charCodeAt(index))
  }
  const dataBytes = samples.length * BYTES_PER_SAMPLE
  ascii(0, 'RIFF')
  view.setUint32(4, 36 + dataBytes, true)
  ascii(8, 'WAVE')
  ascii(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * BYTES_PER_SAMPLE, true)
  view.setUint16(32, BYTES_PER_SAMPLE, true)
  view.setUint16(34, 16, true)
  ascii(36, 'data')
  view.setUint32(40, dataBytes, true)
  return new Blob([header, samples.buffer], { type: 'audio/wav' })
}

/**
 * 有界环形缓冲：`hardFloor = now - maxBufferMs`，`softFloor = speechStart - prerollMs`，
 * 取两者较大者作为裁剪起点。与 demo 的三个默认值逐个对应，不自己发明第四个数。
 */
export class SentAudioRecorder {
  private chunks: Int16Array[] = []

  private totalSamples = 0

  /** 已收到的绝对样本数（不随裁剪减少），以及缓冲区首样本的绝对下标。 */
  private sentSamples = 0

  private startSample = 0

  private speechStartMs = 0

  private truncated = false

  constructor(
    private readonly prerollMs = DEFAULT_PREROLL_MS,
    private readonly maxBufferMs = DEFAULT_MAX_BUFFER_MS
  ) {}

  /** `speech_started`：固定 pre-roll 的起点，让句子开头不被剪掉。 */
  speechStarted(atMs: number): void {
    this.speechStartMs = atMs
  }

  append(samples: Int16Array, atMs: number): void {
    if (!samples.length) return
    this.chunks.push(samples)
    this.totalSamples += samples.length
    this.sentSamples += samples.length
    const hardFloorMs = atMs - this.maxBufferMs
    const softFloorMs = this.speechStartMs ? this.speechStartMs - this.prerollMs : atMs - this.prerollMs
    this.pruneBefore(Math.max(hardFloorMs, softFloorMs))
  }

  /** `speech_stopped`：拼成一段、封成 WAV，然后清空（下一次说话重新计数）。 */
  speechStopped(): SentAudio {
    const samples = new Int16Array(this.totalSamples)
    let offset = 0
    for (const chunk of this.chunks) {
      samples.set(chunk, offset)
      offset += chunk.length
    }
    const result: SentAudio = {
      blob: pcm16ToWavBlob(samples),
      durationMs: Math.round((samples.length / USER_AUDIO_SAMPLE_RATE) * 1000),
      truncated: this.truncated
    }
    this.reset()
    return result
  }

  reset(): void {
    this.chunks = []
    this.totalSamples = 0
    this.sentSamples = 0
    this.startSample = 0
    this.speechStartMs = 0
    this.truncated = false
  }

  /**
   * `floorMs` 是“从录音起点算起的毫秒位置”，不是要保留的样本数量；
   * 负数意味着起点还没到来（新会话、或尚未 speech_started），此时一律不裁。
   */
  private pruneBefore(floorMs: number): void {
    const floorSample = Math.floor((Math.max(0, floorMs) * USER_AUDIO_SAMPLE_RATE) / 1000)
    let cut = floorSample - this.startSample
    while (cut > 0 && this.chunks.length > 0) {
      const head = this.chunks[0]
      this.truncated = true
      if (head.length <= cut) {
        this.chunks.shift()
        this.totalSamples -= head.length
        this.startSample += head.length
        cut -= head.length
      } else {
        this.chunks[0] = head.subarray(cut)
        this.totalSamples -= cut
        this.startSample += cut
        cut = 0
      }
    }
  }
}
