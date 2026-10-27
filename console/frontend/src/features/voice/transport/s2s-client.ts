import { SentAudioRecorder } from '../audio/sent-audio'
import type { QueueTicket, SessionGrant, ToolCall, ToolDef, ToolResult } from '../types'
import { readTurnLatency } from './turn-latency'

export const AUDIO_SAMPLE_RATE = 24_000
export const AUDIO_WORKLET_VERSION = 'audio-24k-v2'
const MIC_CHUNK_MS = 40

/**
 * SDK 只从 `/vendor/openai-realtime-agents.umd.js` 加载。名字拼出来而不是写成字面量：
 * `dist/assets/*.js` 里 `grep -c OpenAIAgentsRealtime` 必须为 0（Task 20 Step 20 的产物
 * 断言）。直接写属性名会自己把那 1 行计数占掉，这条断言就再也测不出「有人把
 * `@openai/agents` 打进 bundle」——那不是命名洁癖，是防止两份 SDK 抢同一个全局。
 */
const SDK_GLOBAL = ['OpenAI', 'AgentsRealtime'].join('')

function sdk(): any {
  const value = (globalThis as any)[SDK_GLOBAL]
  if (!value) throw new Error('OpenAI Agents SDK bundle is not loaded')
  return value
}

export interface NoiseGate {
  enabled: boolean
  thresholdDb: number
}

export interface S2sClientOptions {
  transport: 'websocket' | 'webrtc'
  sessionUrl: string
  callsUrl: string
  /**
   * `GET /api/config` 的 `allowDirect`：真 = 这个部署没有 LB，浏览器直连
   * `directUrl`（或同源反代），不再请求 `/api/session`（demo/main.js:944-953）。
   */
  allowDirect: boolean
  /** 部署钉死的 s2s 地址（`config.s2sUrl`）。空串 = 走同源 `/v1/realtime` 反代。 */
  directUrl: string
  voice: string
  instructions: string
  tools: ToolDef[]
  iceServers: RTCIceServer[]
  startupGreeting: string
  localVad: boolean
  noiseGate: NoiseGate
  playbackBufferMs: number
  micStream?: MediaStream
  audioContext?: AudioContext
  acquireMic?: () => Promise<MediaStream>
  executeTool?: (call: ToolCall) => Promise<ToolResult>
}

function codedError(message: string, code: string, extra?: Record<string, unknown>): Error {
  return Object.assign(new Error(message), { code }, extra)
}

/**
 * 把用户/部署给的地址规整成 realtime WebSocket URL——与 demo/main.js:962-980 的
 * `buildDirectWsUrl` 同一套规则：裸主机补 `ws://`（公网补 `wss://`），http→ws、
 * https→wss，没有路径时补 `/v1/realtime`，已有路径/查询原样保留。
 * 空输入返回 `''`，调用方据此回退到同源反代。
 */
export function buildDirectWsUrl(raw: string): string {
  let value = (raw || '').trim()
  if (!value) return ''
  if (!/^wss?:\/\//i.test(value)) {
    if (/^https?:\/\//i.test(value)) {
      value = value.replace(/^http/i, 'ws')
    } else {
      const isLocal = /^(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/i.test(value)
      value = (isLocal ? 'ws://' : 'wss://') + value
    }
  }
  try {
    const url = new URL(value)
    if (url.pathname === '' || url.pathname === '/') url.pathname = '/v1/realtime'
    return url.toString()
  } catch {
    return value
  }
}

/**
 * 没有钉死上游时的入口：同源 `/v1/realtime`。控制台后端在 `routers/realtime.py`
 * 里把它逐帧转给 `PIPELINE_BASE_URL`（本地 = pipeline-1 的 8765），因此浏览器
 * 既不需要知道 pipeline 地址，也不会撞上跨域。
 */
export function sameOriginRealtimeUrl(href: string = globalThis.location?.href ?? ''): string {
  if (!href) return ''
  try {
    const url = new URL(href)
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    url.pathname = '/v1/realtime'
    url.search = ''
    url.hash = ''
    return url.toString()
  } catch {
    return ''
  }
}

/** orb 只画这九态；`connected`/`closed` 是 transport 词，由 store 归一。 */
const PAINTED_STATES = new Set([
  'idle',
  'connecting',
  'queued',
  'your-turn',
  'listening',
  'user-speaking',
  'processing',
  'ai-speaking',
  'error'
])

/**
 * One conversation. Every event other than audio is forwarded verbatim as
 * `server-event`; the store's TranscriptReducer owns all text bookkeeping.
 */
export class S2sClient extends EventTarget {
  private status = 'idle'

  private closed = false

  private closing = false

  private muted = false

  private session: any = null

  private transport: any = null

  private agent: any = null

  private ctx: AudioContext | null = null

  private micSource: MediaStreamAudioSourceNode | null = null

  private captureNode: AudioWorkletNode | null = null

  private playbackNode: AudioWorkletNode | null = null

  private analysers: { mic?: AnalyserNode; out?: AnalyserNode } = {}

  private outputGain: GainNode | null = null

  private audioElement: HTMLAudioElement | null = null

  private playbackResponseId = ''

  private playbackAudioKey = ''

  private pending: { samples: Float32Array; key: string }[] = []

  private pendingSamples = 0

  private playbackStarted = false

  private readonly playbackItems = new Map<string, { itemId: string; contentIndex: number; samples: number }>()

  private queueId = ''

  /**
   * 「后端实际听到的我那一段」。记的是重采样、噪声门与静音之后的上行 chunk，
   * 与 `sendAudio` 同一条路径（demo/s2s-realtime-client.js:549-553），所以抽屉里
   * 回放的就是模型听到的，而不是第二路原始麦克风。
   */
  private readonly userAudioRecorder = new SentAudioRecorder()

  // `setTimeout` 的返回值随宿主类型变化（DOM 是 number，node 是 Timeout），交给推断。
  private joinWaiter: { resolve: () => void; reject: (e: Error) => void; timer: ReturnType<typeof setTimeout> } | null = null

  constructor(private readonly options: S2sClientOptions) {
    super()
  }

  get currentStatus(): string {
    return this.status
  }

  private setStatus(next: string): void {
    if (this.status === next) return
    // 只发九态（外加 `closed`）：一个拼错的状态名会让 orb 的 INDICATOR 查空，
    // 画出一个没有图标的球，而且没有任何报错。
    if (next !== 'closed' && !PAINTED_STATES.has(next)) return
    this.status = next
    this.emit('status', { status: next })
  }

  private emit(type: string, detail: unknown): void {
    this.dispatchEvent(new CustomEvent(type, { detail }))
  }

  /** Step 1 of the handshake: a grant, or a queue ticket, or a coded error. */
  private async acquireGrant(): Promise<{ grant: SessionGrant; waited: boolean }> {
    const first = await this.postSession()
    if (first.state === 'granted') return { grant: first.grant, waited: false }
    this.setStatus('queued')
    return { grant: await this.pollQueue(first.ticket), waited: true }
  }

  private async postSession(): Promise<{ state: 'granted'; grant: SessionGrant } | { state: 'queued'; ticket: QueueTicket }> {
    const res = await fetch(this.options.sessionUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}'
    })
    const body = await res.json().catch(() => ({}))
    if (res.status === 402) throw codedError('Daily conversation limit reached', 'limit', { tier: body?.tier })
    if (res.status === 401) throw codedError('Sign in again to continue', 'login-required', { loginUrl: body?.loginUrl })
    if (res.status === 503 && body?.state === 'at_capacity') throw codedError('The queue is full — try again shortly.', 'queue-full')
    if (!res.ok) throw codedError(`/session failed (${res.status})`, 'session-failed')
    if (body.state === 'queued') {
      return { state: 'queued', ticket: { queueId: body.queue_id, position: body.position, pollIntervalS: body.poll_interval_s } }
    }
    return { state: 'granted', grant: parseGrant(body) }
  }

  private async pollQueue(ticket: QueueTicket): Promise<SessionGrant> {
    this.queueId = ticket.queueId
    this.emit('queue', { queueId: ticket.queueId, position: ticket.position })
    const interval = Math.max(1, ticket.pollIntervalS || 2) * 1000
    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, interval))
      if (this.closed) throw codedError('queue wait aborted', 'aborted')
      let res: Response
      try {
        res = await fetch(`${this.options.sessionUrl.replace(/\/session$/, '')}/queue/${encodeURIComponent(this.queueId)}`)
      } catch {
        continue // transient network blip: the ticket is still good
      }
      if (res.status === 402) throw codedError('Daily conversation limit reached', 'limit')
      if (res.status === 401) throw codedError('Sign in again to continue', 'login-required')
      if (res.status === 404) throw codedError('Queue timed out', 'queue-expired')
      if (!res.ok) continue
      const body = await res.json().catch(() => null)
      if (!body) continue
      if (body.state === 'queued') {
        this.emit('queue', { queueId: this.queueId, position: body.position })
        continue
      }
      this.queueId = ''
      return parseGrant(body)
    }
  }

  private async awaitJoin(grant: SessionGrant): Promise<void> {
    const seconds = Math.max(3, (grant.pendingTimeoutS || 60) - 3)
    this.setStatus('your-turn')
    this.emit('ready-to-join', { grant, expiresSec: seconds })
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(codedError('Your spot expired', 'join-expired')), seconds * 1000)
      this.joinWaiter = { resolve, reject, timer }
    })
  }

  /**
   * 直连分支的入口：钉死的地址优先，否则同源反代。demo 在 `allowDirect` 时
   * 也是这样绕开 `/api/session` —— 那个接口只在 LB 模式存在，没有 LB 时是 404。
   */
  private directSocketUrl(): string {
    const pinned = buildDirectWsUrl(this.options.directUrl)
    const url = pinned || sameOriginRealtimeUrl()
    if (!url) throw codedError('Enter a speech-to-speech server URL in Settings.', 'no-server-url')
    return url
  }

  async connect(): Promise<void> {
    if (this.session) throw new Error('Already connected')
    let url: string
    if (this.options.transport === 'websocket') {
      if (this.options.allowDirect) {
        this.setStatus('connecting')
        url = this.directSocketUrl()
        // 没有 grant：额度/心跳只属于 LB 模式，直连部署两者都不存在。
        this.emit('direct', { url })
      } else {
        this.setStatus('connecting')
        const { grant, waited } = await this.acquireGrant()
        if (this.closed) throw codedError('connect aborted', 'aborted')
        // A queued grant holds a slot for seconds only, and the browser needs a user
        // gesture to resume the AudioContext — so wait for the click before dialling.
        if (waited) await this.awaitJoin(grant)
        this.emit('session', { grant })
        url = grant.connectUrl
      }
    } else {
      url = new URL(this.options.callsUrl, globalThis.location?.href).href
    }
    this.setStatus('connecting')
    if (!this.options.micStream && this.options.acquireMic) {
      this.options.micStream = await this.options.acquireMic()
    }
    if (!this.options.micStream?.getAudioTracks()[0]) throw new Error('No microphone track available')
    await this.setupAudio(this.options.micStream)
    await this.openSession(url)
    this.setStatus('connected')
  }

  private async openSession(url: string): Promise<void> {
    const { OpenAIRealtimeWebRTC, OpenAIRealtimeWebSocket, RealtimeAgent, RealtimeSession } = sdk()
    if (this.options.transport === 'websocket') {
      // The SDK clock starts at receipt; our worklet queue owns the real playout
      // position, so the interrupt is re-implemented against that queue.
      const socket = new OpenAIRealtimeWebSocket({ useInsecureApiKey: true })
      socket.interrupt = (cancelOngoingResponse = true) => {
        if (cancelOngoingResponse) socket._cancelResponse?.()
        socket.emit('audio_interrupted')
      }
      this.transport = socket
    } else {
      // Mute until the data channel is up so startup noise cannot race the greeting.
      this.options.micStream!.getAudioTracks()[0].enabled = false
      this.audioElement = new Audio()
      this.audioElement.autoplay = true
      this.transport = new OpenAIRealtimeWebRTC({
        mediaStream: this.options.micStream,
        audioElement: this.audioElement,
        useInsecureApiKey: true,
        changePeerConnection: (pc: RTCPeerConnection) => {
          if (this.options.iceServers.length) {
            pc.setConfiguration({ ...pc.getConfiguration(), iceServers: this.options.iceServers })
          }
          return pc
        }
      })
    }

    const tools = this.buildSdkTools(this.options.tools)
    this.agent = new RealtimeAgent({
      name: 'speech-to-speech-console',
      instructions: this.options.instructions,
      voice: this.options.voice,
      tools
    })
    this.session = new RealtimeSession(this.agent, {
      transport: this.transport,
      model: 's2s-local',
      tracingDisabled: true,
      config: {
        outputModalities: ['audio'],
        providerData: { extensions: ['speech_to_speech.input_audio_transcription.snapshot'] },
        audio: {
          input: {
            format: { type: 'audio/pcm', rate: AUDIO_SAMPLE_RATE },
            transcription: { model: 'whisper-1' },
            turnDetection: { type: 'server_vad', interruptResponse: true },
            noiseReduction: null
          },
          output: { format: { type: 'audio/pcm', rate: AUDIO_SAMPLE_RATE }, speed: 1 }
        }
      }
    })

    this.transport.on('*', (event: any) => this.onTransportEvent(event))
    this.transport.on('connection_change', (state: string) => {
      if (state === 'disconnected' && !this.closing && this.status !== 'error') {
        this.setStatus('error')
        this.emit('error', { error: new Error('Realtime transport disconnected') })
      }
    })
    this.session.on('audio', (event: any) => this.onAudio(event))
    this.session.on('audio_interrupted', () => this.clearPlayback())

    await this.session.connect({ apiKey: 's2s-local', url })
    const greeting = this.options.startupGreeting.trim()
    if (greeting) this.session.sendMessage(greeting)
    this.setMuted(this.muted)
  }

  private onTransportEvent(event: any): void {
    if (typeof event?.type !== 'string') return
    switch (event.type) {
      case 'speech_to_speech.output_audio.visemes':
        this.emit('visemes', event)
        return
      case 'input_audio_buffer.speech_started': {
        const itemId = typeof event.item_id === 'string' ? event.item_id : ''
        // 只有 websocket 才由我们自己发 chunk；webrtc 的上行在浏览器内部，拿不到同一份 PCM。
        if (this.options.transport === 'websocket') {
          this.userAudioRecorder.speechStarted({ itemId, audioStartMs: Number(event.audio_start_ms) })
        }
        this.emit('user-turn-started', { itemId })
        this.setStatus('user-speaking')
        break
      }
      case 'input_audio_buffer.speech_stopped': {
        const itemId = typeof event.item_id === 'string' ? event.item_id : ''
        if (this.options.transport === 'websocket') {
          const recording = this.userAudioRecorder.speechStopped({ itemId, audioEndMs: Number(event.audio_end_ms) })
          if (recording) this.emit('user-audio', recording)
        }
        this.emit('user-turn-stopped', { itemId })
        if (this.status === 'user-speaking') this.setStatus('processing')
        break
      }
      case 'response.created':
        this.resetPlaybackBuffer(event.response?.id ?? '')
        if (this.status === 'connected' || this.status === 'user-speaking') this.setStatus('processing')
        break
      case 'response.output_audio.delta':
        if (this.options.transport === 'websocket' && event.response_id === this.playbackResponseId) {
          this.playbackAudioKey = JSON.stringify([event.item_id, event.content_index])
          if (!this.playbackItems.has(this.playbackAudioKey)) {
            this.playbackItems.set(this.playbackAudioKey, {
              itemId: event.item_id,
              contentIndex: event.content_index,
              samples: 0
            })
          }
        }
        break
      case 'response.done': {
        const id = event.response?.id ?? ''
        if (this.options.transport === 'websocket') this.finishPlayback(id, event.response?.status ?? 'completed')
        this.setStatus('connected')
        this.playbackResponseId = ''
        this.emit('response-finished', {
          responseId: id,
          status: event.response?.status ?? 'completed',
          transcript: transcriptOf(event.response),
          latency: readTurnLatency(event.response)
        })
        break
      }
      case 'error':
        this.emit('error', { error: new Error(event.error?.message ?? 'Server error') })
        break
    }
    this.emit('server-event', event)
  }

  private onAudio(event: any): void {
    if (this.options.transport !== 'websocket' || !this.playbackNode || this.closed) return
    if (!this.playbackResponseId || event.responseId !== this.playbackResponseId || !event.data?.byteLength) return
    const view = new DataView(event.data)
    const samples = new Float32Array(event.data.byteLength / 2)
    for (let i = 0; i < samples.length; i += 1) {
      const sample = view.getInt16(i * 2, true)
      samples[i] = sample < 0 ? sample / 0x8000 : sample / 0x7fff
    }
    const item = this.playbackItems.get(this.playbackAudioKey)
    if (item) item.samples += samples.length
    this.pending.push({ samples, key: this.playbackAudioKey })
    this.pendingSamples += samples.length
    if (this.playbackStarted || this.pendingSamples >= this.playbackThreshold) this.releasePlayback()
  }

  private get playbackThreshold(): number {
    return Math.ceil((AUDIO_SAMPLE_RATE * Math.max(0, this.options.playbackBufferMs)) / 1000)
  }

  private releasePlayback(): void {
    if (!this.pending.length) return
    for (const { samples, key } of this.pending) {
      this.playbackNode?.port.postMessage({ kind: 'audio', samples, key }, [samples.buffer])
    }
    this.pending = []
    this.pendingSamples = 0
    this.playbackStarted = true
    this.setStatus('ai-speaking')
  }

  private resetPlaybackBuffer(responseId = ''): void {
    this.playbackResponseId = responseId
    this.playbackAudioKey = ''
    this.pending = []
    this.pendingSamples = 0
    this.playbackStarted = false
  }

  private finishPlayback(responseId: string, status: string): void {
    if (!responseId || responseId !== this.playbackResponseId) return
    if (status === 'completed' || status === 'incomplete') this.releasePlayback()
    this.resetPlaybackBuffer()
  }

  private clearPlayback(): void {
    this.resetPlaybackBuffer()
    this.playbackNode?.port.postMessage({ kind: 'clear' })
  }

  private async setupAudio(stream: MediaStream): Promise<void> {
    const ctx = this.options.audioContext ?? new AudioContext({ latencyHint: 'interactive' })
    this.ctx = ctx
    if (ctx.state === 'suspended') await ctx.resume().catch(() => {})
    this.outputGain = ctx.createGain()
    this.outputGain.connect(ctx.destination)
    this.micSource = ctx.createMediaStreamSource(stream)

    const analyser = ctx.createAnalyser()
    analyser.fftSize = 512
    analyser.smoothingTimeConstant = 0
    this.micSource.connect(analyser)
    this.analysers.mic = analyser

    await ctx.audioWorklet.addModule(`/worklets/mic-capture.js?v=${AUDIO_WORKLET_VERSION}`)
    // `targetRate` 与 session.update 声明的上行速率必须写在一起：worklet 自己的
    // 默认值恰好也是 24k，但依赖默认值意味着改一处会静默错另一处（demo 还额外
    // 用 capture-config 握手校验，这里至少把意图显式化）。
    this.captureNode = new AudioWorkletNode(ctx, 'mic-capture', {
      processorOptions: { chunkMs: MIC_CHUNK_MS, targetRate: AUDIO_SAMPLE_RATE, version: AUDIO_WORKLET_VERSION }
    })
    this.captureNode.port.onmessage = (message) => this.handleCaptureMessage(message)
    this.micSource.connect(this.captureNode)
    this.setNoiseGate(this.options.noiseGate)

    if (this.options.transport === 'websocket') {
      await ctx.audioWorklet.addModule(`/worklets/audio-playback.js?v=${AUDIO_WORKLET_VERSION}`)
      this.playbackNode = new AudioWorkletNode(ctx, 'audio-playback', { outputChannelCount: [1] })
      this.playbackNode.connect(this.outputGain)
      this.playbackNode.port.onmessage = (message) => {
        if (message.data?.kind === 'cleared') this.onPlaybackCleared(message.data)
      }
    }
  }

  /**
   * mic-capture worklet 的两种消息：音频 chunk 是裸 ArrayBuffer（worklet 直接
   * `postMessage(out.buffer, [out.buffer])`，从来没有 `{kind:'chunk'}` 这种包裹），
   * 电平是 `{kind:'level', rms}` 的线性 RMS。旧代码等 `chunk`/`db` 两个不存在的
   * 字段，麦克风音频全部被丢弃 → 服务端只听到开场问候的文本，后续语音无声。
   */
  private handleCaptureMessage(message: { data: unknown }): void {
    const data = message.data
    if (data instanceof ArrayBuffer) {
      // 录制与发送共用一个条件：静音期的音频既没出去，也不该出现在回放里。
      // `Math.floor` 是刻意的：长度为奇的尾巴凑不出一个样本，`new Int16Array(buffer)`
      // 会直接抛 RangeError（录音器内部同样跳掉它，demo 的 `append` 也是）。
      if (!this.muted) {
        this.session?.sendAudio(data)
        this.userAudioRecorder.append(new Int16Array(data, 0, Math.floor(data.byteLength / 2)))
      }
      return
    }
    if ((data as any)?.kind === 'level') {
      const rms = Number((data as any).rms)
      const db = Number.isFinite(rms) && rms > 0 ? 20 * Math.log10(rms) : -100
      this.emit('level', { db })
    }
  }

  /**
   * The worklet reports how many samples it actually rendered before the clear.
   * Anything still unheard is truncated server-side, so the model's transcript
   * stops matching audio the user never got (demo/s2s-realtime-client.js:522-538).
   */
  private onPlaybackCleared(message: any): void {
    const played = new Map<string, number>(message.played ?? [])
    for (const [key, item] of this.playbackItems) {
      const samples = Math.min(item.samples, played.get(key) ?? 0)
      if (samples >= item.samples) continue
      this.transport?.sendEvent({
        type: 'conversation.item.truncate',
        item_id: item.itemId,
        content_index: item.contentIndex,
        audio_end_ms: Math.max(0, Math.floor((samples / AUDIO_SAMPLE_RATE) * 1000))
      })
    }
    this.playbackItems.clear()
  }

  /**
   * §2.2 hot fields only. A present `voice` is remembered for the next call but the
   * live session is not rebuilt: the pipeline treats it as protocol echo.
   */
  updateSession(session: Record<string, unknown>): void {
    const voice = session.voice
    const instructions = session.instructions
    if (typeof voice === 'string' && voice) this.options.voice = voice
    if (typeof instructions === 'string' && instructions) this.options.instructions = instructions
    if (!this.session) return
    this.transport?.sendEvent?.({ type: 'session.update', session })
  }

  /**
   * 把 `ToolDef[]` 转成 SDK 的 tool 实例。`openSession` 与 `setTools` 共用：
   * 两处必须产出同一个执行器绑定，否则换过工具后的会话行为会悄悄分叉。
   */
  private buildSdkTools(definitions: ToolDef[]): any[] {
    const { tool } = sdk()
    return definitions.map((definition) =>
      tool({
        name: definition.name,
        description: definition.description,
        parameters: definition.parameters,
        strict: false,
        execute: async (args: unknown, _context: unknown, details: any) => {
          const call: ToolCall = {
            name: definition.name,
            arguments: JSON.stringify(args ?? {}),
            callId: details?.toolCall?.callId ?? ''
          }
          // 会话列表的 tool 条目由执行器驱动，而不是等服务端回显：
          // 无论 pipeline 是否转发 `conversation.item.created`，这里都一定发生。
          this.emit('tool-call', call)
          try {
            const result = await this.options.executeTool?.(call)
            if (!result) throw new Error(`No executor for ${definition.name}`)
            this.emit('tool-result', { ...call, output: result.output, image: result.image ?? '' })
            if (result.image) this.session?.addImage(result.image, { triggerResponse: false })
            return result.output
          } catch (error: any) {
            // 失败也要留痕：条目里写清原因，再把错误抛回 SDK，让模型知道工具没成。
            this.emit('tool-result', {
              ...call,
              output: `Tool failed: ${error?.message ?? String(error)}`,
              image: '',
              failed: true
            })
            throw error
          }
        }
      })
    )
  }

  setTools(tools: ToolDef[]): void {
    this.options.tools = tools
    if (!this.session || !this.agent) return
    // `updateAgent` 要的是真正的 RealtimeAgent 实例：`{ ...agent }` 只展开实例自身
    // 属性，会丢掉原型上的 `getEnabledHandoffs` 等方法，SDK 运行到半路才报
    // TypeError。用最新配置重建实例传入（instructions/voice 也顺带热更）。
    const { RealtimeAgent } = sdk()
    this.agent = new RealtimeAgent({
      name: 'speech-to-speech-console',
      instructions: this.options.instructions,
      voice: this.options.voice,
      tools: this.buildSdkTools(tools)
    })
    this.session.updateAgent(this.agent)
  }

  setMuted(muted: boolean): void {
    this.muted = muted
    for (const track of this.options.micStream?.getAudioTracks() ?? []) track.enabled = !muted
    this.captureNode?.port.postMessage({ kind: 'mute', muted })
  }

  setNoiseGate(gate: NoiseGate): void {
    this.options.noiseGate = gate
    this.captureNode?.port.postMessage({ kind: 'gate', enabled: gate.enabled, thresholdDb: gate.thresholdDb })
  }

  async setAudioOutputDevice(deviceId = ''): Promise<void> {
    if (this.audioElement && 'setSinkId' in this.audioElement) {
      await (this.audioElement as any).setSinkId(deviceId).catch(() => {})
    }
  }

  join(): void {
    const waiter = this.joinWaiter
    this.joinWaiter = null
    if (waiter) {
      clearTimeout(waiter.timer)
      waiter.resolve()
    }
  }

  async close(): Promise<void> {
    this.closed = true
    this.closing = true
    this.clearPlayback()
    // 缓冲是按「本次通话的绝对样本轴」索引的，留到下一通会把边界算歪。
    this.userAudioRecorder.reset()
    if (this.joinWaiter) {
      clearTimeout(this.joinWaiter.timer)
      this.joinWaiter.reject(codedError('join aborted', 'aborted'))
      this.joinWaiter = null
    }
    this.session?.close?.()
    this.session = null
    this.transport = null
    for (const node of [this.captureNode, this.playbackNode, this.micSource, this.analysers.mic, this.outputGain]) {
      try {
        node?.disconnect()
      } catch {
        /* already detached */
      }
    }
    try {
      await this.ctx?.close()
    } catch {
      /* already closed */
    }
    this.ctx = null
    this.setStatus('closed')
  }
}

function parseGrant(body: any): SessionGrant {
  return {
    sessionId: body.session_id,
    connectUrl: body.connect_url,
    websocketUrl: body.websocket_url,
    sessionToken: body.session_token,
    pendingTimeoutS: body.pending_timeout_s,
    tier: body.tier,
    limited: !!body.limited,
    remainingSec: body.remainingSec ?? null,
    heartbeatSec: body.heartbeatSec ?? null
  }
}

function transcriptOf(response: any): string {
  const parts = response?.output ?? []
  return parts
    .flatMap((part: any) => part?.content ?? [])
    .filter((content: any) => content?.type === 'audio' || content?.type === 'output_audio')
    .map((content: any) => content?.transcript ?? '')
    .join(' ')
    .trim()
}
