/**
 * 浏览器侧把录音变成后端能收的 WAV：16 kHz / 单声道 / PCM16。
 *
 * 这三条不是风格问题——后端用标准库 `wave` 校验（§3.11.2 步骤 2），采样率或声道
 * 不符就 400 `voice_audio_invalid`。`MediaRecorder` 给的是 webm/opus，所以必须
 * 解码 + 重采样后再自己写 44 字节头。
 */
export const TARGET_RATE = 16000

function writeAscii(view: DataView, offset: number, text: string): void {
  for (let index = 0; index < text.length; index += 1) {
    view.setUint8(offset + index, text.charCodeAt(index))
  }
}

/** PCM16 编码：44 字节头 + 16 bit 小端样本。 */
export function encodeWav(samples: Float32Array, sampleRate: number = TARGET_RATE): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  writeAscii(view, 0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeAscii(view, 8, 'WAVE')
  writeAscii(view, 12, 'fmt ')
  view.setUint32(16, 16, true) // fmt 块长度
  view.setUint16(20, 1, true) // 1 = PCM
  view.setUint16(22, 1, true) // 单声道
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // byteRate = rate * blockAlign
  view.setUint16(32, 2, true) // blockAlign = 声道 * 位深 / 8
  view.setUint16(34, 16, true)
  writeAscii(view, 36, 'data')
  view.setUint32(40, samples.length * 2, true)

  let offset = 44
  for (const sample of samples) {
    const clamped = Math.max(-1, Math.min(1, sample))
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true)
    offset += 2
  }
  return new Blob([buffer], { type: 'audio/wav' })
}

/** 录音 → 16 kHz 单声道 WAV。`OfflineAudioContext(1, …)` 顺带完成下混。 */
export async function toWav(recorded: Blob): Promise<Blob> {
  const context = new AudioContext()
  try {
    const decoded = await context.decodeAudioData(await recorded.arrayBuffer())
    const frames = Math.max(1, Math.ceil(decoded.duration * TARGET_RATE))
    const offline = new OfflineAudioContext(1, frames, TARGET_RATE)
    const source = offline.createBufferSource()
    source.buffer = decoded
    source.connect(offline.destination)
    source.start()
    const rendered = await offline.startRendering()
    return encodeWav(rendered.getChannelData(0))
  } finally {
    void context.close()
  }
}
