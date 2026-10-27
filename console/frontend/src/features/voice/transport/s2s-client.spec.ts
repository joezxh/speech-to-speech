import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { buildDirectWsUrl, sameOriginRealtimeUrl, S2sClient } from '@/features/voice/transport/s2s-client'

// 这两支函数决定声音到底拨向哪里：直连模式（没有 LB）不再请求 `/api/session`，
// 而是把部署钉死的地址、或同源 `/v1/realtime` 交给 WebSocket。规则与
// demo/main.js:962-980 同源，这里逐条钉住，免得回归时静默改地址。

describe('buildDirectWsUrl', () => {
  it('is empty when the deployment pins nothing (caller falls back to same origin)', () => {
    expect(buildDirectWsUrl('')).toBe('')
    expect(buildDirectWsUrl('   ')).toBe('')
  })

  it('turns a loopback http URL into ws + /v1/realtime', () => {
    expect(buildDirectWsUrl('http://127.0.0.1:8765')).toBe('ws://127.0.0.1:8765/v1/realtime')
    expect(buildDirectWsUrl('http://localhost:8765/')).toBe('ws://localhost:8765/v1/realtime')
  })

  it('accepts a bare host:port — localhost stays ws, anything else gets wss', () => {
    expect(buildDirectWsUrl('localhost:8765')).toBe('ws://localhost:8765/v1/realtime')
    expect(buildDirectWsUrl('s2s.example.com')).toBe('wss://s2s.example.com/v1/realtime')
  })

  it('maps https to wss without touching a public https address', () => {
    expect(buildDirectWsUrl('https://s2s.example.com')).toBe('wss://s2s.example.com/v1/realtime')
  })

  it('keeps an explicit ws/wss path and query instead of appending one', () => {
    expect(buildDirectWsUrl('ws://127.0.0.1:8765/v1/realtime')).toBe('ws://127.0.0.1:8765/v1/realtime')
    expect(buildDirectWsUrl('wss://s2s.example.com/custom?lang=zh')).toBe('wss://s2s.example.com/custom?lang=zh')
  })
})

describe('sameOriginRealtimeUrl', () => {
  it('dials the console proxy that forwards to PIPELINE_BASE_URL', () => {
    expect(sameOriginRealtimeUrl('http://localhost:3000/console/params?x=1')).toBe('ws://localhost:3000/v1/realtime')
    expect(sameOriginRealtimeUrl('https://s2s.example.com/')).toBe('wss://s2s.example.com/v1/realtime')
  })

  it('is empty when there is no page location to derive from', () => {
    expect(sameOriginRealtimeUrl('')).toBe('')
  })
})

// 回归：热更新工具时 `updateAgent` 必须拿到真正的 RealtimeAgent 实例。
// 旧实现 `{ ...agent, tools }` 只展开实例自身属性，丢掉原型上的
// getEnabledHandoffs 等方法，SDK 在会话中途抛 TypeError。
describe('setTools', () => {
  // 与 s2s-client.ts 同一套约定：全局名拼出来而不是写字面量。
  const SDK_GLOBAL = ['OpenAI', 'AgentsRealtime'].join('')

  class RealtimeAgent {
    constructor(public readonly config: any) {}

    async getEnabledHandoffs(): Promise<unknown[]> {
      return []
    }
  }

  let updateAgent: ReturnType<typeof vi.spyOn>
  let session: { updateAgent: ReturnType<typeof vi.fn> }

  beforeEach(() => {
    session = { updateAgent: vi.fn() }
    updateAgent = session.updateAgent
    ;(globalThis as any)[SDK_GLOBAL] = {
      RealtimeAgent,
      tool: (definition: any) => ({ ...definition, __tool: true })
    }
  })

  afterEach(() => {
    delete (globalThis as any)[SDK_GLOBAL]
  })

  // session/agent 是实例自有字段，只能在具体实例上注入。
  function wiredClient(): any {
    const client: any = new S2sClient({ transport: 'websocket', tools: [] } as any)
    client.session = session
    client.agent = new RealtimeAgent({ name: 'seed', tools: [] })
    return client
  }

  it('passes a live RealtimeAgent instance (prototype methods included) to updateAgent', () => {
    wiredClient().setTools([{ name: 'lookup', description: 'd', parameters: {} }])

    expect(updateAgent).toHaveBeenCalledTimes(1)
    const passed = updateAgent.mock.calls[0][0] as any
    expect(passed).toBeInstanceOf(RealtimeAgent)
    expect(passed.getEnabledHandoffs).toBeTypeOf('function')
    const tools = passed.config.tools
    expect(tools).toHaveLength(1)
    expect(tools[0]).toMatchObject({ name: 'lookup', description: 'd', parameters: {}, __tool: true })
    expect(tools[0].execute).toBeTypeOf('function')
  })

  it('is a no-op before a session exists', () => {
    const client: any = new S2sClient({ transport: 'websocket', tools: [] } as any)
    client.setTools([{ name: 'lookup', description: 'd', parameters: {} }])
    expect(updateAgent).not.toHaveBeenCalled()
  })
})

// 回归：麦克风上行断链。mic-capture worklet 用 postMessage(out.buffer, [out.buffer])
// 投递裸 ArrayBuffer（任何版本都是），而消费端等待 `{kind:'chunk'}` 永远不成立，
// 音频全部被丢弃 → 服务端 VAD 听不到任何用户语音，只有走文本消息的开场问候
// 能得到回答。level 消息同理：worklet 带的是线性 rms，消费契约是 dB。
describe('capture message handling', () => {
  function wiredClient(): any {
    const client: any = new S2sClient({ transport: 'websocket', tools: [] } as any)
    client.session = { sendAudio: vi.fn() }
    return client
  }

  it('forwards a raw ArrayBuffer mic chunk to the session', () => {
    const client = wiredClient()
    const buffer = new ArrayBuffer(1920)
    client.handleCaptureMessage({ data: buffer })
    expect(client.session.sendAudio).toHaveBeenCalledTimes(1)
    expect(client.session.sendAudio).toHaveBeenCalledWith(buffer)
  })

  it('does not forward chunks while muted', () => {
    const client = wiredClient()
    client.muted = true
    client.handleCaptureMessage({ data: new ArrayBuffer(1920) })
    expect(client.session.sendAudio).not.toHaveBeenCalled()
  })

  it('converts the worklet rms into the dB axis the meter speaks', () => {
    const client = wiredClient()
    const levels: any[] = []
    client.addEventListener('level', (event: CustomEvent) => levels.push(event.detail))
    client.handleCaptureMessage({ data: { kind: 'level', rms: 0.1 } })
    // 20·log10(0.1) = -20 dB；门限与表条都用 dB（features/voice/audio/meter.ts）。
    expect(levels).toHaveLength(1)
    expect(levels[0].db).toBeCloseTo(-20, 5)
    client.handleCaptureMessage({ data: { kind: 'level', rms: 0 } })
    expect(levels[1].db).toBe(-100)
  })

  it('ignores unrelated worklet messages', () => {
    const client = wiredClient()
    client.handleCaptureMessage({ data: { kind: 'capture-config', inputRate: 48000 } })
    expect(client.session.sendAudio).not.toHaveBeenCalled()
  })
})

// 抽屉里那一行「播放我的原音」的数据源：客户端必须把*真正发出去*的 PCM 缓存起来，
// 在服务端 VAD 的两个边界之间切出 WAV，并以 `user-audio` 交给 store。
// 语义与事件名对齐 demo/s2s-realtime-client.js:577-604 —— 只有 websocket 录音
// （webrtc 的上行由浏览器自己管，拿不到同一份 chunk），但 `user-turn-*` 两种 transport 都发，
// 因为气泡的语音占位不区分传输方式。
describe('user audio recording', () => {
  /** 24kHz 下 4800 个样本 = 200ms 的静音帧。 */
  function micChunk(): ArrayBuffer {
    return new Int16Array(4800).buffer
  }

  function wiredClient(transport: 'websocket' | 'webrtc' = 'websocket'): any {
    const client: any = new S2sClient({ transport, tools: [] } as any)
    client.session = { sendAudio: vi.fn() }
    return client
  }

  function collect(client: any): Record<string, any[]> {
    const seen: Record<string, any[]> = { turns: [], audio: [] }
    client.addEventListener('user-turn-started', (event: CustomEvent) => seen.turns.push(['started', event.detail]))
    client.addEventListener('user-turn-stopped', (event: CustomEvent) => seen.turns.push(['stopped', event.detail]))
    client.addEventListener('user-audio', (event: CustomEvent) => seen.audio.push(event.detail))
    return seen
  }

  it('slices the sent pcm between speech_started and speech_stopped into a wav', () => {
    const client = wiredClient()
    const seen = collect(client)

    client.handleCaptureMessage({ data: micChunk() })
    client.onTransportEvent({ type: 'input_audio_buffer.speech_started', item_id: 'item_1', audio_start_ms: 0 })
    client.handleCaptureMessage({ data: micChunk() })
    client.onTransportEvent({ type: 'input_audio_buffer.speech_stopped', item_id: 'item_1', audio_end_ms: 400 })

    expect(seen.turns).toEqual([
      ['started', { itemId: 'item_1' }],
      ['stopped', { itemId: 'item_1' }]
    ])
    expect(seen.audio).toHaveLength(1)
    expect(seen.audio[0].itemId).toBe('item_1')
    // 边界说的是「从本次上行第一个样本算起的绝对毫秒」：0 → 400ms = 9600 个样本。
    expect(seen.audio[0].durationMs).toBeCloseTo(400, 3)
    expect(seen.audio[0].truncated).toBe(false)
    expect(seen.audio[0].blob.type).toBe('audio/wav')
    // 44 字节 WAV 头 + 9600 个 PCM16 样本。
    expect(seen.audio[0].blob.size).toBe(44 + 9600 * 2)
  })

  it('does not record chunks the session never received', () => {
    const client = wiredClient()
    const seen = collect(client)

    client.onTransportEvent({ type: 'input_audio_buffer.speech_started', item_id: 'item_1', audio_start_ms: 0 })
    client.muted = true
    client.handleCaptureMessage({ data: micChunk() })
    client.muted = false
    client.handleCaptureMessage({ data: micChunk() })
    client.onTransportEvent({ type: 'input_audio_buffer.speech_stopped', item_id: 'item_1', audio_end_ms: 200 })

    // 只有没静音的那一帧进了缓冲：200ms，而不是静音期的 400ms。
    expect(seen.audio[0].durationMs).toBeCloseTo(200, 3)
  })

  it('emits nothing when the backend never opened a speech item', () => {
    const client = wiredClient()
    const seen = collect(client)

    client.handleCaptureMessage({ data: micChunk() })
    client.onTransportEvent({ type: 'input_audio_buffer.speech_stopped', item_id: 'item_1', audio_end_ms: 100 })

    expect(seen.audio).toHaveLength(0)
    expect(seen.turns).toEqual([['stopped', { itemId: 'item_1' }]])
  })

  it('still announces turn boundaries over webrtc but records no audio there', () => {
    const client = wiredClient('webrtc')
    const seen = collect(client)

    client.handleCaptureMessage({ data: micChunk() })
    client.onTransportEvent({ type: 'input_audio_buffer.speech_started', item_id: 'item_1', audio_start_ms: 0 })
    client.onTransportEvent({ type: 'input_audio_buffer.speech_stopped', item_id: 'item_1', audio_end_ms: 100 })

    expect(seen.audio).toHaveLength(0)
    expect(seen.turns).toEqual([
      ['started', { itemId: 'item_1' }],
      ['stopped', { itemId: 'item_1' }]
    ])
  })
})
