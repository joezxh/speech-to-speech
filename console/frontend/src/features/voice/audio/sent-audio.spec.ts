import { describe, expect, it } from 'vitest'

import { pcm16ToWavBlob, SentAudioRecorder, USER_AUDIO_SAMPLE_RATE } from './sent-audio'

// 语义基准：demo/ws/user-audio-recorder.js。录音器缓存的是「真正发给后端的 PCM」，
// VAD 边界（audio_start_ms / audio_end_ms）按样本下标切片；同一 item 的投机续接
// 会把多段拼接成一份 WAV（与聊天视图「一条 item 一行」保持一致）。

/** 生成 `ms` 毫秒的 pcm16（24 kHz），并填入可辨识的非零样本。 */
function chunk(ms: number): Int16Array {
  const samples = new Int16Array(Math.round((ms * USER_AUDIO_SAMPLE_RATE) / 1000))
  samples.fill(7)
  return samples
}

/** 把 recorder 的 blob 读回样本数。 */
async function samplesOf(blob: Blob): Promise<number> {
  const view = new DataView(await blob.arrayBuffer())
  return (view.byteLength - 44) / 2
}

describe('pcm16ToWavBlob', () => {
  it('writes a 44-byte RIFF/WAVE header around the PCM', async () => {
    const blob = pcm16ToWavBlob(new Int16Array(480))
    const view = new DataView(await blob.arrayBuffer())
    expect(blob.type).toBe('audio/wav')
    expect(view.getUint32(4, true)).toBe(36 + 960)
    expect(view.getUint32(24, true)).toBe(USER_AUDIO_SAMPLE_RATE)
  })
})

describe('SentAudioRecorder', () => {
  it('keeps the pre-roll that arrived before speech_started', () => {
    const recorder = new SentAudioRecorder()
    recorder.append(chunk(2000))
    // 服务端的 audio_start_ms 指回语音 onset：这里语音从 0ms 开始，所以 pre-roll 全保留。
    recorder.speechStarted({ itemId: 'i1', audioStartMs: 0 })
    recorder.append(chunk(1000))
    const result = recorder.speechStopped({ itemId: 'i1', audioEndMs: undefined })
    expect(result).not.toBeNull()
    expect(result!.truncated).toBe(false)
    // 边界没给 end 时用已收到的样本收尾：2000ms pre-roll + 1000ms 语音。
    expect(result!.durationMs).toBeCloseTo(3000, 0)
  })

  it('slices exactly between audioStartMs and audioEndMs', () => {
    const recorder = new SentAudioRecorder(5000, 120_000)
    recorder.append(chunk(1000)) // 0–1000ms
    recorder.append(chunk(1000)) // 1000–2000ms
    recorder.append(chunk(1000)) // 2000–3000ms
    recorder.speechStarted({ itemId: 'i1', audioStartMs: 1000 })
    const result = recorder.speechStopped({ itemId: 'i1', audioEndMs: 3000 })
    expect(result!.durationMs).toBeCloseTo(2000, 0)
  })

  it('returns null without an active speech_started', () => {
    const recorder = new SentAudioRecorder()
    recorder.append(chunk(500))
    expect(recorder.speechStopped({ itemId: 'i9' })).toBeNull()
  })

  it('accumulates speculative continuations of the same item into one WAV', () => {
    const recorder = new SentAudioRecorder()
    recorder.append(chunk(500))
    recorder.speechStarted({ itemId: 'a', audioStartMs: 0 })
    recorder.append(chunk(500))
    const first = recorder.speechStopped({ itemId: 'a', audioEndMs: 1000 })
    recorder.speechStarted({ itemId: 'a', audioStartMs: 1000 })
    recorder.append(chunk(400))
    const second = recorder.speechStopped({ itemId: 'a', audioEndMs: 1400 })
    // demo：同 item 重开时携带拼接后的完整录音，播放器始终一份、逐段变长。
    expect(first!.durationMs).toBeCloseTo(1000, 0)
    expect(second!.durationMs).toBeCloseTo(1400, 0)
  })

  it('drops the previous recording when a new item starts', () => {
    const recorder = new SentAudioRecorder()
    recorder.append(chunk(500))
    recorder.speechStarted({ itemId: 'a', audioStartMs: 0 })
    recorder.append(chunk(500))
    recorder.speechStopped({ itemId: 'a', audioEndMs: 1000 })
    recorder.speechStarted({ itemId: 'b', audioStartMs: 1000 })
    recorder.append(chunk(700))
    const result = recorder.speechStopped({ itemId: 'b', audioEndMs: 1700 })
    expect(result!.durationMs).toBeCloseTo(700, 0)
  })

  it('prunes past maxBuffer and flags truncated', async () => {
    const recorder = new SentAudioRecorder(1000, 5000)
    recorder.speechStarted({ itemId: 'a', audioStartMs: 0 })
    for (let at = 1000; at <= 12_000; at += 1000) recorder.append(chunk(1000))
    const result = recorder.speechStopped({ itemId: 'a', audioEndMs: 12_000 })
    expect(result!.truncated).toBe(true)
    expect(result!.durationMs).toBeLessThan(12_000)
    expect(await samplesOf(result!.blob)).toBeGreaterThan(0)
  })

  it('ignores odd-length tails that cannot form a sample', () => {
    const recorder = new SentAudioRecorder()
    recorder.append(new Int16Array(0))
    recorder.speechStarted({ itemId: 'a', audioStartMs: 0 })
    recorder.append(chunk(300))
    const result = recorder.speechStopped({ itemId: 'a', audioEndMs: 300 })
    expect(result!.durationMs).toBeCloseTo(300, 0)
  })
})
