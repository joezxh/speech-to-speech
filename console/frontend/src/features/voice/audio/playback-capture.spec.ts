import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PlaybackCapture, downmixToMono, floatToPcm16, resampleLinear } from './playback-capture'
import type { DecodedAudio } from './playback-capture'

function decoded(sampleRate: number, channels: Float32Array[]): DecodedAudio {
  const length = channels[0].length
  return {
    numberOfChannels: channels.length,
    length,
    sampleRate,
    getChannelData: (channel: number) => channels[channel] ?? new Float32Array(length)
  }
}

describe('downmixToMono', () => {
  it('averages the channels', () => {
    const mono = downmixToMono(decoded(48_000, [new Float32Array([1, -1, 0.5]), new Float32Array([-1, 1, 0.5])]))
    expect(Array.from(mono)).toEqual([0, 0, 0.5])
  })

  it('copies a mono buffer instead of handing back the AudioBuffer-owned array', () => {
    const data = new Float32Array([0.25, 0.5])
    const mono = downmixToMono(decoded(48_000, [data]))
    expect(Array.from(mono)).toEqual([0.25, 0.5])
    // The caller turns this into PCM; a shared buffer would let a later decode rewrite it.
    data[0] = 0
    expect(mono[0]).toBe(0.25)
  })
})

describe('resampleLinear', () => {
  it('halves a 48k signal to 24k', () => {
    const out = resampleLinear(new Float32Array([0, 1, 2, 3, 4, 5]), 48_000, 24_000)
    expect(Array.from(out)).toEqual([0, 2, 4])
  })

  it('is a no-op when the rate already matches and when the input is empty', () => {
    const same = new Float32Array([0.1, 0.2])
    expect(resampleLinear(same, 24_000, 24_000)).toBe(same)
    expect(resampleLinear(new Float32Array(0), 48_000, 24_000).length).toBe(0)
  })

  it('interpolates between samples instead of dropping them', () => {
    const out = resampleLinear(new Float32Array([0, 1]), 24_000, 48_000)
    expect(out.length).toBe(4)
    expect(out[1]).toBeCloseTo(0.5, 5)
    expect(out[2]).toBeCloseTo(1, 5)
  })
})

describe('floatToPcm16', () => {
  it('keeps the negative half-scale it came from and clamps what is over', () => {
    const pcm = floatToPcm16(new Float32Array([-1, 1, -2, 2, 0]))
    expect(Array.from(pcm)).toEqual([-32768, 32767, -32768, 32767, 0])
  })
})

/**
 * The class is only exercised through the two seams it actually depends on: the
 * element's capture call and `decodeAudioData`. Everything else is the browser's.
 */
class FakeStream {
  stopped = 0

  getAudioTracks(): { stop(): void }[] {
    return [{ stop: () => void (this.stopped += 1) }]
  }
}

class FakeRecorder {
  static readonly instances: FakeRecorder[] = []

  static isTypeSupported = () => true

  state = 'inactive'

  mimeType = 'audio/webm;codecs=opus'

  ondataavailable: ((event: { data: Blob }) => void) | null = null

  onstop: (() => void) | null = null

  onerror: ((event: Event) => void) | null = null

  constructor(readonly stream: FakeStream) {
    FakeRecorder.instances.push(this)
  }

  start(): void {
    this.state = 'recording'
  }

  stop(): void {
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob([new Uint8Array([1, 2, 3, 4])], { type: 'audio/webm' }) })
    this.onstop?.()
  }
}

function elementWithCapture(stream: FakeStream): HTMLAudioElement {
  return { captureStream: () => stream } as unknown as HTMLAudioElement
}

function capture(seconds = 0.1, rate = 48_000): { capture: PlaybackCapture; decode: ReturnType<typeof vi.fn> } {
  const samples = Math.round(seconds * rate)
  const tone = new Float32Array(samples)
  for (let index = 0; index < samples; index += 1) tone[index] = 0.5
  const decode = vi.fn(async () => decoded(rate, [tone]))
  return { capture: new PlaybackCapture(elementWithCapture(new FakeStream()), { decodeAudioData: decode }), decode }
}

beforeEach(() => {
  FakeRecorder.instances.length = 0
  ;(globalThis as any).MediaRecorder = FakeRecorder
})

afterEach(() => {
  delete (globalThis as any).MediaRecorder
})

describe('PlaybackCapture', () => {
  it('refuses to start when the element cannot be captured', () => {
    const instance = new PlaybackCapture({} as HTMLAudioElement, { decodeAudioData: async () => decoded(48_000, [new Float32Array(1)]) })
    expect(instance.supported).toBe(false)
    expect(instance.start()).toBe(false)
  })

  it('refuses to start when there is no MediaRecorder at all', () => {
    delete (globalThis as any).MediaRecorder
    expect(capture().capture.supported).toBe(false)
  })

  it('records a reply into a mono 16-bit WAV at the pipeline rate', async () => {
    const { capture: instance, decode } = capture(0.1)
    expect(instance.start()).toBe(true)
    expect(instance.running).toBe(true)

    const audio = await instance.stop()
    expect(decode).toHaveBeenCalledTimes(1)
    expect(instance.running).toBe(false)
    expect(audio).not.toBeNull()
    // 0.1 s at 48 kHz downmixed and resampled to 24 kHz.
    expect(Math.round(audio!.durationMs)).toBe(100)
    expect(audio!.blob.size).toBe(44 + 2_400 * 2)

    const header = new DataView((await audio!.blob.arrayBuffer()).slice(0, 44))
    expect(String.fromCharCode(header.getUint8(0), header.getUint8(1), header.getUint8(2), header.getUint8(3))).toBe('RIFF')
    expect(header.getUint16(22, true)).toBe(1) // mono
    expect(header.getUint16(34, true)).toBe(16) // 16-bit
    expect(header.getUint32(24, true)).toBe(24_000)
  })

  it('gives up quietly when the container cannot be decoded', async () => {
    const instance = new PlaybackCapture(elementWithCapture(new FakeStream()), {
      decodeAudioData: async () => {
        throw new Error('decode failed')
      }
    })
    instance.start()
    expect(await instance.stop()).toBeNull()
  })

  it('stops nothing that never started', async () => {
    const instance = capture(0.05).capture
    expect(await instance.stop()).toBeNull()
    expect(FakeRecorder.instances).toHaveLength(0)
  })

  it('releases the captured track only at the end of the connection', async () => {
    const stream = new FakeStream()
    const instance = new PlaybackCapture(elementWithCapture(stream), { decodeAudioData: async () => decoded(24_000, [new Float32Array(0)]) })
    instance.start()
    await instance.stop()
    expect(stream.stopped).toBe(0)

    instance.start()
    instance.dispose()
    expect(stream.stopped).toBe(1)
    expect(await instance.stop()).toBeNull()
    expect(instance.start()).toBe(false)
  })
})
