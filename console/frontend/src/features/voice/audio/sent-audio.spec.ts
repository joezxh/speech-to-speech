import { describe, expect, it } from 'vitest'

import { pcm16ToWavBlob, SentAudioRecorder, USER_AUDIO_SAMPLE_RATE } from './sent-audio'

const chunk = (ms: number): Int16Array => new Int16Array(Math.round((ms * USER_AUDIO_SAMPLE_RATE) / 1000))

describe('pcm16ToWavBlob', () => {
  it('writes a 44-byte RIFF/WAVE header around the PCM', async () => {
    const blob = pcm16ToWavBlob(new Int16Array(480))
    const view = new DataView(await blob.arrayBuffer())
    expect(blob.type).toBe('audio/wav')
    expect(view.getUint32(4, true)).toBe(36 + 960)
    expect(view.getUint32(24, true)).toBe(USER_AUDIO_SAMPLE_RATE)
  })

  it('encodes duration from sample count, not from wall clock', () => {
    const recorder = new SentAudioRecorder()
    recorder.append(chunk(3000), 3000)
    expect(recorder.speechStopped().durationMs).toBe(3000)
  })
})

describe('SentAudioRecorder', () => {
  it('keeps the pre-roll before speech_started', () => {
    const recorder = new SentAudioRecorder()
    recorder.append(chunk(2000), 2000)
    recorder.speechStarted(2000)
    recorder.append(chunk(1000), 3000)
    const audio = recorder.speechStopped()
    expect(audio.truncated).toBe(false)
    expect(audio.durationMs).toBe(3000)
  })

  it('prunes past maxBuffer and flags truncated', () => {
    const recorder = new SentAudioRecorder(1000, 5000)
    for (let at = 1000; at <= 12000; at += 1000) recorder.append(chunk(1000), at)
    const audio = recorder.speechStopped()
    expect(audio.truncated).toBe(true)
    expect(audio.durationMs).toBeLessThan(12000)
  })

  it('does not leak one utterance into the next', () => {
    const recorder = new SentAudioRecorder()
    recorder.append(chunk(500), 500)
    recorder.speechStopped()
    recorder.append(chunk(700), 700)
    expect(recorder.speechStopped().durationMs).toBe(700)
  })
})
