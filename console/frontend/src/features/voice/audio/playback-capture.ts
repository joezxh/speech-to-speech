/**
 * WebRTC 下的助手侧录音。
 *
 * websocket 有 `response.output_audio.delta` 可以攒（`ResponseAudioRecorder`）；
 * webrtc 的那一份走浏览器内部的 RTP 轨道，由 SDK 直接塞进 `<audio>` 元素播放，
 * 事件流里一个字节都看不见。唯一的取回点就是那个元素：`captureStream()` 把它正在
 * 放的音抓成一路线，`MediaRecorder` 录下来，再把容器解成单声道 PCM16 包成 WAV。
 *
 * 链路每一步都可能缺能力（Safari 没有 `captureStream`、`MediaRecorder` 不认这个
 * 容器、解码失败）。全部退化成 `null`：归档那一行就是今天的 `audio_state='none'`，
 * 抓到了是额外收获，抓不到不是故障。
 *
 * 采到的不是模型发出的原始 PCM，而是**真的放出来的那一份**——被插话掐掉的结尾
 * 在这里就是没有，与上行 `SentAudioRecorder`「记真正发出去的那一段」同一个语义。
 */
import { pcm16ToWavBlob, USER_AUDIO_SAMPLE_RATE } from './sent-audio'

/**
 * 落盘采样率沿用 pipeline 的 24k（`AUDIO_SAMPLE_RATE`），不是浏览器的 48k：
 * 后端对单轮音频有字节上限，24k 单声道能把可录时长整整翻倍。
 */
const CAPTURE_SAMPLE_RATE = USER_AUDIO_SAMPLE_RATE

/** Chrome/Edge 走 webm，Firefox 走 ogg；都不认就交给浏览器自己选默认容器。 */
const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus']

/**
 * `MediaRecorder.stop()` 到 `stop` 事件通常几十毫秒；真卡住时不能把
 * `response-finished`（以及那一行的转写）无限拖下去。
 */
export const CAPTURE_STOP_TIMEOUT_MS = 2_000

export interface CapturedAudio {
  blob: Blob
  durationMs: number
}

/** 解码结果里用得上的四样，测试可以拿普通对象顶替 `AudioBuffer`。 */
export interface DecodedAudio {
  readonly numberOfChannels: number
  readonly length: number
  readonly sampleRate: number
  getChannelData(channel: number): Float32Array
}

/** 整个类只用到 `decodeAudioData`，所以只依赖这一格能力。 */
export interface AudioDecoder {
  decodeAudioData(data: ArrayBuffer): Promise<DecodedAudio>
}

/** 多声道取平均。`AudioBuffer.getChannelData` 的所有权在 buffer 上，必须复制。 */
export function downmixToMono(buffer: DecodedAudio): Float32Array {
  const length = Math.max(0, buffer.length)
  const channels = Math.max(1, buffer.numberOfChannels)
  if (channels === 1) return buffer.getChannelData(0).slice(0, length)
  const mono = new Float32Array(length)
  for (let channel = 0; channel < channels; channel += 1) {
    const data = buffer.getChannelData(channel)
    for (let index = 0; index < length; index += 1) mono[index] += data[index]
  }
  for (let index = 0; index < length; index += 1) mono[index] /= channels
  return mono
}

/**
 * 线性插值重采样。不做抗混叠滤波：这份音频的用途是归档回放与转写对照，
 * 不是声纹模板（那边用的是 `voice_service` 的 16k 校验），省下的复杂度换得到的收益。
 */
export function resampleLinear(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (!input.length || fromRate <= 0 || toRate <= 0 || fromRate === toRate) return input
  const ratio = fromRate / toRate
  const output = new Float32Array(Math.max(1, Math.floor(input.length / ratio)))
  for (let index = 0; index < output.length; index += 1) {
    const position = index * ratio
    const lower = Math.floor(position)
    const upper = Math.min(lower + 1, input.length - 1)
    const fraction = position - lower
    output[index] = input[lower] * (1 - fraction) + input[upper] * fraction
  }
  return output
}

/** 与 `s2s-client` 的 PCM→float 对称：负半轴除以 0x8000，正半轴乘以 0x7fff。 */
export function floatToPcm16(input: Float32Array): Int16Array {
  const pcm = new Int16Array(input.length)
  for (let index = 0; index < input.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, input[index]))
    pcm[index] = sample < 0 ? Math.round(sample * 0x8000) : Math.round(sample * 0x7fff)
  }
  return pcm
}

/**
 * `HTMLMediaElement.captureStream` 至今不在 TS 的 DOM 声明里（Firefox 只有
 * `mozCaptureStream`），所以只能按名字取。
 */
function captureSourceOf(element: HTMLAudioElement): (() => MediaStream) | null {
  const candidate = element as HTMLAudioElement & { captureStream?: () => MediaStream; mozCaptureStream?: () => MediaStream }
  const pick = candidate.captureStream ?? candidate.mozCaptureStream
  return typeof pick === 'function' ? pick.bind(candidate) : null
}

function supportedMimeType(): string {
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') return ''
  return MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type)) ?? ''
}

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  if (!(ms > 0)) return promise
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`capture did not stop within ${ms}ms`)), ms)
    promise.then(
      (value) => {
        clearTimeout(timer)
        resolve(value)
      },
      (error: unknown) => {
        clearTimeout(timer)
        reject(error)
      }
    )
  })
}

export class PlaybackCapture {
  /**
   * 一路连接只抓一次：同一个元素上反复 `captureStream()` 再停轨道，Chrome 会让
   * 后面的抓取拿不到声音。轨道要等 `dispose()` 才停，`MediaRecorder` 才是每条回复一个。
   */
  private stream: MediaStream | null = null

  private recorder: MediaRecorder | null = null

  /**
   * 当前这一条回复的切片。数组本体被 `ondataavailable` 的闭包握着，
   * 所以 `stop()` 只能拿引用、不能先把 `this.chunks` 换掉：
   * 最后一块数据恰恰是在 `recorder.stop()` 里推进来的。
   */
  private chunks: Blob[] = []

  private disposed = false

  constructor(private readonly element: HTMLAudioElement, private readonly decoder: AudioDecoder) {}

  /** 三样凑齐才有得抓：元素的抓取口、`MediaRecorder`、能解码的 context。 */
  get supported(): boolean {
    return (
      !this.disposed &&
      typeof MediaRecorder !== 'undefined' &&
      captureSourceOf(this.element) !== null &&
      typeof this.decoder?.decodeAudioData === 'function'
    )
  }

  get running(): boolean {
    return Boolean(this.recorder)
  }

  /** 抓不到就返回 `false`：调用方照常走，这一行最多是没有音频。 */
  start(): boolean {
    if (this.disposed) return false
    if (this.recorder) return true
    if (!this.supported) return false
    if (!this.stream) {
      try {
        this.stream = captureSourceOf(this.element)?.() ?? null
      } catch {
        this.stream = null
      }
    }
    if (!this.stream) return false
    try {
      const mimeType = supportedMimeType()
      const recorder = mimeType ? new MediaRecorder(this.stream, { mimeType }) : new MediaRecorder(this.stream)
      const chunks: Blob[] = []
      this.chunks = chunks
      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data?.size) chunks.push(event.data)
      }
      recorder.start()
      this.recorder = recorder
      return true
    } catch {
      this.recorder = null
      return false
    }
  }

  /**
   * `response.done`：收尾这一条回复的录音并解码成 WAV。
   * 没有任何录音在跑时立刻 `null`，调用方不必等一个空转的 await。
   */
  async stop(timeoutMs = CAPTURE_STOP_TIMEOUT_MS): Promise<CapturedAudio | null> {
    const recorder = this.recorder
    this.recorder = null
    if (!recorder) return null
    // 拿引用、不拿副本：下面 `recorder.stop()` 推出的最后一块必须算在内。
    const chunks = this.chunks
    this.chunks = []
    try {
      if (recorder.state !== 'inactive') {
        await withTimeout(
          new Promise<void>((resolve, reject) => {
            recorder.onstop = () => resolve()
            recorder.onerror = (event: Event) => reject((event as any).error ?? new Error('MediaRecorder failed'))
            recorder.stop()
          }),
          timeoutMs
        )
      }
    } catch {
      return null
    } finally {
      recorder.ondataavailable = null
      recorder.onstop = null
      recorder.onerror = null
    }
    if (!chunks.length) return null
    return this.toWav(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }))
  }

  /** 连接结束：停录制、放轨道。之后再 `start()` 也不会动。 */
  dispose(): void {
    this.disposed = true
    const recorder = this.recorder
    this.recorder = null
    this.chunks = []
    try {
      if (recorder && recorder.state !== 'inactive') recorder.stop()
    } catch {
      /* already stopped */
    }
    for (const track of this.stream?.getAudioTracks?.() ?? []) track.stop()
    this.stream = null
  }

  private async toWav(blob: Blob): Promise<CapturedAudio | null> {
    if (this.disposed || !blob.size) return null
    let decoded: DecodedAudio
    try {
      decoded = await this.decoder.decodeAudioData(await blob.arrayBuffer())
    } catch {
      // 解不开自己录的容器（浏览器换 codec 了、或者一个样本都没落进来）就等于没录。
      return null
    }
    const mono = downmixToMono(decoded)
    const pcm = floatToPcm16(resampleLinear(mono, decoded.sampleRate, CAPTURE_SAMPLE_RATE))
    if (!pcm.length) return null
    return {
      blob: pcm16ToWavBlob(pcm, CAPTURE_SAMPLE_RATE),
      durationMs: (pcm.length / CAPTURE_SAMPLE_RATE) * 1000
    }
  }
}
