/**
 * 缓存「真正发给后端的 PCM」，把服务端的 VAD 边界换算成可回放的 WAV。
 * 语义基准：`demo/ws/user-audio-recorder.js`——它记的是重采样、噪声门之后的信号，
 * 所以回放出来的就是后端实际听到的那段，不是第二路原始麦克风。
 */

/** pipeline 上行采样率，不是浏览器的 48kHz。 */
export const USER_AUDIO_SAMPLE_RATE = 24000
const BYTES_PER_SAMPLE = 2
const DEFAULT_PREROLL_MS = 5000
const DEFAULT_MAX_BUFFER_MS = 120_000

export interface SpeechStartedBoundary {
  itemId?: string
  /** 服务端认定的语音起点（绝对毫秒，从本次上行音频的第一个样本算起）。 */
  audioStartMs?: number
}

export interface SpeechStoppedBoundary {
  itemId?: string
  audioEndMs?: number
}

export interface SentAudio {
  /** 归属的会话条目：与转写、气泡用同一个 id，抽屉里才能落到同一行。 */
  itemId: string
  blob: Blob
  /** 同一 item 的投机续接会把多段拼起来，所以这里是累计长度，不是本段长度。 */
  durationMs: number
  /** 边界要求的起点已经被缓冲剪掉了：条目要显示 `· beginning unavailable`。 */
  truncated: boolean
}

/** 一段已发送音频在绝对样本轴上的位置。 */
interface StoredChunk {
  startSample: number
  endSample: number
  bytes: Uint8Array
}

interface ActiveSegment {
  itemId: string
  requestedStartSample: number
}

function concatBytes(first: Uint8Array, second: Uint8Array): Uint8Array {
  const result = new Uint8Array(first.byteLength + second.byteLength)
  result.set(first, 0)
  result.set(second, first.byteLength)
  return result
}

/**
 * 把小端单声道 PCM16 包进标准 WAV 容器。
 * 样本先复制一份：`subarray` 与原始 buffer 共享内存，直接拿去写会带进脏数据。
 */
export function pcm16ToWavBlob(pcm: Int16Array, sampleRate = USER_AUDIO_SAMPLE_RATE): Blob {
  const samples = new Int16Array(pcm)
  const dataBytes = samples.length * BYTES_PER_SAMPLE
  const header = new ArrayBuffer(44)
  const view = new DataView(header)
  const ascii = (offset: number, text: string): void => {
    for (let index = 0; index < text.length; index += 1) view.setUint8(offset + index, text.charCodeAt(index))
  }
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
 * 有界环形缓冲，两个裁剪下限取较大者：
 * - `hardFloor`：总量不超过 `maxBufferMs`；
 * - `softFloor`：活动段用它要求的起点（更早的已经没用了），没有活动段时留 `prerollMs`，
 *   好让晚到的 `speech_started` 还能往回切到语音 onset。
 */
export class SentAudioRecorder {
  private chunks: StoredChunk[] = []

  /** 已收到的绝对样本数，只增不减——裁剪靠下标切片，不靠移动时间轴。 */
  private sentSamples = 0

  private active: ActiveSegment | null = null

  private lastItemId = ''

  private lastItemPcm: Uint8Array = new Uint8Array(0)

  constructor(
    private readonly prerollMs = DEFAULT_PREROLL_MS,
    private readonly maxBufferMs = DEFAULT_MAX_BUFFER_MS,
    private readonly sampleRate = USER_AUDIO_SAMPLE_RATE
  ) {}

  /** 记下一帧实际发出去的 PCM；长度为奇的尾巴直接丢掉，凑不出一个样本。 */
  append(samples: Int16Array): void {
    const byteLength = samples.byteLength
    const evenLength = byteLength - (byteLength % BYTES_PER_SAMPLE)
    if (evenLength <= 0) return
    const bytes = new Uint8Array(samples.buffer, samples.byteOffset, evenLength).slice()
    const startSample = this.sentSamples
    this.chunks.push({ startSample, endSample: startSample + evenLength / BYTES_PER_SAMPLE, bytes })
    this.sentSamples = startSample + evenLength / BYTES_PER_SAMPLE
    this.prune()
  }

  /**
   * `speech_started`：记住服务端说的语音起点。这个事件通常在服务端确认之后才到，
   * 所以靠 pre-roll 保证起点之前的音频还没被剪掉。
   */
  speechStarted(boundary: SpeechStartedBoundary): void {
    const itemId = boundary.itemId || `audio_${this.sentSamples}`
    this.active = { itemId, requestedStartSample: this.sampleAtMs(boundary.audioStartMs, this.sentSamples) }
    if (itemId !== this.lastItemId) {
      this.lastItemId = itemId
      this.lastItemPcm = new Uint8Array(0)
    }
    this.prune()
  }

  /**
   * `speech_stopped`：切出这一段的 PCM 拼进该 item 的累计录音。带同一个 `item_id`
   * 的续接会把后一段接在前一段后面（与聊天视图「一条 item 一行」保持一致），
   * 所以播放器始终只有一个，只是逐次变长。
   */
  speechStopped(boundary: SpeechStoppedBoundary): SentAudio | null {
    const active = this.active
    if (!active) return null
    this.active = null

    const itemId = boundary.itemId || active.itemId
    const availableStart = this.chunks.length ? this.chunks[0].startSample : this.sentSamples
    const startSample = Math.max(active.requestedStartSample, availableStart)
    let endSample = this.sampleAtMs(boundary.audioEndMs, this.sentSamples)
    // 边界给得比起点还早（或刚好相等）时不按零长度收尾，改用已收到的样本。
    if (endSample <= startSample) endSample = this.sentSamples
    endSample = Math.min(endSample, this.sentSamples)

    const segment = this.slice(startSample, endSample)
    if (segment.byteLength === 0) {
      this.prune()
      return null
    }
    if (itemId !== this.lastItemId) {
      this.lastItemId = itemId
      this.lastItemPcm = new Uint8Array(0)
    }
    this.lastItemPcm = concatBytes(this.lastItemPcm, segment)
    const result: SentAudio = {
      itemId,
      blob: pcm16ToWavBlob(new Int16Array(this.lastItemPcm.buffer, this.lastItemPcm.byteOffset, this.lastItemPcm.byteLength / BYTES_PER_SAMPLE), this.sampleRate),
      durationMs: (this.lastItemPcm.byteLength / BYTES_PER_SAMPLE / this.sampleRate) * 1000,
      truncated: active.requestedStartSample < availableStart
    }
    this.prune()
    return result
  }

  reset(): void {
    this.chunks = []
    this.sentSamples = 0
    this.active = null
    this.lastItemId = ''
    this.lastItemPcm = new Uint8Array(0)
  }

  /** 毫秒 → 绝对样本下标；缺失、非法或越界都退回 fallback，并夹在 `[0, sentSamples]`。 */
  private sampleAtMs(ms: number | undefined, fallback: number): number {
    if (!Number.isFinite(ms as number) || Number(ms) < 0) return fallback
    return Math.max(0, Math.min(Math.round((Number(ms) * this.sampleRate) / 1000), this.sentSamples))
  }

  private slice(startSample: number, endSample: number): Uint8Array {
    const parts: Uint8Array[] = []
    let length = 0
    for (const chunk of this.chunks) {
      const overlapStart = Math.max(startSample, chunk.startSample)
      const overlapEnd = Math.min(endSample, chunk.endSample)
      if (overlapEnd <= overlapStart) continue
      const part = chunk.bytes.slice(
        (overlapStart - chunk.startSample) * BYTES_PER_SAMPLE,
        (overlapEnd - chunk.startSample) * BYTES_PER_SAMPLE
      )
      parts.push(part)
      length += part.byteLength
    }
    const result = new Uint8Array(length)
    let offset = 0
    for (const part of parts) {
      result.set(part, offset)
      offset += part.byteLength
    }
    return result
  }

  /** 整块丢弃落在下限以下的 chunk，不做块内切割：下标切片本来就跳得过。 */
  private prune(): void {
    const hardFloor = Math.max(0, this.sentSamples - Math.round((this.sampleRate * this.maxBufferMs) / 1000))
    const softFloor = this.active
      ? this.active.requestedStartSample
      : Math.max(0, this.sentSamples - Math.round((this.sampleRate * this.prerollMs) / 1000))
    const floor = Math.max(hardFloor, softFloor)
    while (this.chunks.length && this.chunks[0].endSample <= floor) this.chunks.shift()
  }
}
