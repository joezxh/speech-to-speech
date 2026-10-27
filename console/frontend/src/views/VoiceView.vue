<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { endSessionBeacon, getDemoConfig, getMe, heartbeat, leaveQueueBeacon, search } from '@/api/demo'
import { acquireMic, releaseMic } from '@/features/voice/audio/capture'
import { GATE_OFF_DB, SpeakingDetector } from '@/features/voice/audio/meter'
import { startLocalVad } from '@/features/voice/audio/vad'
import BubbleStack from '@/features/voice/components/BubbleStack.vue'
import CameraPip from '@/features/voice/components/CameraPip.vue'
import HistoryDrawer from '@/features/voice/components/HistoryDrawer.vue'
import IdentityBlock from '@/features/voice/components/IdentityBlock.vue'
import LimitDialog from '@/features/voice/components/LimitDialog.vue'
import MicGate from '@/features/voice/components/MicGate.vue'
import OrbStage from '@/features/voice/components/OrbStage.vue'
import QueueOverlay from '@/features/voice/components/QueueOverlay.vue'
import SettingsDialog from '@/features/voice/components/SettingsDialog.vue'
import ToolsDialog from '@/features/voice/components/ToolsDialog.vue'
import { openCamera, snapshot } from '@/features/voice/tools/camera'
import { useBubbles } from '@/features/voice/useBubbles'
import { buildDirectWsUrl, S2sClient } from '@/features/voice/transport/s2s-client'
import type { ToolCallRecord, ToolResultRecord } from '@/features/voice/transport/events'
import type { SentAudio } from '@/features/voice/audio/sent-audio'
import type { ToolCall, ToolDef, TurnLatency, VoiceSettings } from '@/features/voice/types'
import { useShellStore } from '@/stores/shell'
import { useVoiceStore } from '@/stores/voice'
import type { VoiceStatus } from '@/stores/voice'

const store = useVoiceStore()
const shell = useShellStore()

/**
 * 侧栏的 History / Tools / Settings 是「打开浮层」的动作，不是路由（§3.2.4）：
 * 外壳只把选择写进 `shell.voiceOverlay`，页面负责打开对应的抽屉/对话窗并立刻清空选择。
 */
watch(
  () => shell.voiceOverlay,
  (overlay) => {
    if (overlay === 'history') store.openHistory()
    if (overlay === 'tools') toolsOpen.value = true
    if (overlay === 'settings') {
      settingsOpen.value = true
      void refreshDevices()
    }
    if (overlay) shell.closeOverlay()
  },
  // `immediate`：从侧栏语音组跨页点浮层时，`ConsoleLayout` 会先写 `voiceOverlay` 再
  // 导航到本页；挂载时需立即消费这个已置位的请求。
  { immediate: true }
)

// 参考 demo：舞台右侧只有一叠转瞬即逝的气泡（`#bubble-stack`）。
// 会话文字列表（历史抽屉）是纯手动入口——顶栏的 History 按钮，不再随接通自动弹出。

/**
 * 顶栏的账号 chip 现在由 `ConsoleLayout` 直接渲染（不再 Teleport 注入），额度按钮通过
 * `shell.limitOpen` 把请求递进来。
 */
watch(
  () => shell.limitOpen,
  (open) => {
    if (!open) return
    limitOpen.value = true
    shell.closeLimit()
  }
)

/** 回放用户原音时静音上行，停止后按当前静音钮状态恢复（demo 的 `userAudioReplaying`）。 */
function onReplay(playing: boolean): void {
  client?.setMuted(playing || muted.value)
}

/** demo/index.html 的九个 voice：顺序与值都不能变，它会进 session.update。 */
const VOICES = ['Aiden', 'Ryan', 'Dylan', 'Eric', 'Ono_Anna', 'Serena', 'Sohee', 'Uncle_Fu', 'Vivian']

const settingsOpen = ref(false)
const toolsOpen = ref(false)
const limitOpen = ref(false)
const micError = ref('')
const levelDb = ref(-100)
const notice = ref('')
const expiresSec = ref(60)
const muted = ref(false)
const queueFull = ref(false)
const inputs = ref<Array<{ id: string; label: string }>>([])
const outputs = ref<Array<{ id: string; label: string }>>([])
/** 用户自带的 Serper key：**只在内存里**，不进 localStorage，也不进 URL（B5）。 */
const searchKey = ref('')

let client: S2sClient | null = null
let mic: MediaStream | null = null
let vad: { destroy: () => Promise<void> } | null = null
let heartbeatTimer = 0
const detector = new SpeakingDetector()
const camPip = ref<InstanceType<typeof CameraPip> | null>(null)
/**
 * 必须是 ref：`CameraPip` 的 `v-if` 只依赖它。写成普通变量时 `startCamera()` 把流拿到手
 * 也不会触发重渲染，PiP 永远挂不上（`camPip.value` 恒为 null）。
 */
const camStream = ref<MediaStream | null>(null)

const MIC_ERRORS: Record<string, string> = {
  'mic-denied': 'Microphone access was blocked. Allow it from your browser address bar, then retry.',
  'mic-missing': 'No microphone found. Plug one in or pick another input in Settings.',
  'mic-failed': 'The microphone could not be opened. Retry, or pick another input in Settings.'
}

const CONNECT_ERRORS: Record<string, string> = {
  limit: "You're out of minutes for today — they reset daily.",
  'login-required': 'Sign in again to continue.',
  'queue-full': 'The waiting line is full. Try again in a minute.',
  'queue-expired': 'Your spot in line expired.',
  'join-expired': 'Your spot expired before you joined.',
  aborted: ''
}

const serverKey = computed(() => store.config.search)
const searchAvailable = computed(() => serverKey.value || Boolean(searchKey.value))
/**
 * 设置里展示的其实不是“用户输入的地址”，而是本次会话真正 dial 的那一刻（demo 也把
 * 这个字段做成只读）。直连模式列出 ws 地址，LB 模式列出授权接口，二者都不是猜的。
 */
const serverUrl = computed(() => {
  if (!store.config.allowDirect) return '/api/session → load balancer'
  return buildDirectWsUrl(store.config.s2sUrl) || `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/v1/realtime`
})
// 上游地址被钉死时 WebRTC 的 /api/calls 代理也只转发那一个地址，因此传输方式不可选。
const transportLocked = computed(() => !store.config.allowDirect)
/** WebRTC 需要服务端能直连 SDP 入口；同源反代只有 WS 一条路（rtc=false）。 */
const rtcAvailable = computed(() => Boolean(store.config.rtc) && !transportLocked.value)

const caption = computed(() => {
  if (micError.value) return MIC_ERRORS[micError.value] ?? micError.value
  if (notice.value) return notice.value
  switch (store.state) {
    case 'idle': return 'Tap to start'
    case 'connecting': return 'Connecting'
    case 'queued': return `Queued · position ${store.queue?.position ?? '—'}`
    case 'your-turn': return "You're up!"
    case 'listening':
    case 'user-speaking': return 'Listening'
    case 'processing': return 'Thinking'
    case 'ai-speaking': return 'Speaking'
    case 'error': return 'Tap to retry'
    default: return ''
  }
})
const subCaption = computed(() =>
  store.state === 'queued' ? 'Every slot is busy, so we saved you a spot. Hang tight, you’re moving up.' : ''
)
const captionTone = computed<'info' | 'error'>(() => (micError.value || notice.value || store.state === 'error' ? 'error' : 'info'))

const tools = computed<ToolDef[]>(() => {
  const list: ToolDef[] = []
  if (store.settings.tools.web && searchAvailable.value) {
    list.push({
      type: 'function',
      name: 'web_search',
      description: 'Search the web for current or factual information. Returns results with titles, snippets and URLs.',
      parameters: { type: 'object', properties: { query: { type: 'string' } }, required: ['query'] }
    })
  }
  if (store.settings.tools.camera) {
    list.push({
      type: 'function',
      name: 'camera_snapshot',
      description: "Capture a frame from the user's webcam when they refer to something visual.",
      parameters: { type: 'object', properties: {}, required: [] }
    })
  }
  return list
})

const limitCopy = computed(() => {
  const paid = store.me.tier === 'pro' || store.me.tier === 'org'
  return paid
    ? {
        title: "That's a wrap for now",
        message: 'Your organisation has used today’s shared minutes.',
        ctaLabel: 'Back to the space',
        ctaHref: '/',
        note: 'Daily caps keep the shared pool healthy for everyone.'
      }
    : {
        title: "That's a wrap for now",
        message: 'You have used your free minutes for today.',
        ctaLabel: 'Sign in for more time',
        ctaHref: store.me.loginUrl || 'https://huggingface.co/subscribe/pro',
        note: 'Free minutes reset every day.'
      }
})

/**
 * demo 的 `#bubble-stack`：语音占位 → 增量改写 → 各自到期淡出，栈深 3。
 * 行为全部在 `useBubbles` 里（带单测），页面只把客户端事件接上去。
 */
const {
  items: bubbleItems,
  userTurnStarted,
  userTurnStopped,
  userTranscript,
  assistantTranscript,
  toolCall: showToolBubble,
  assistantActivity,
  responseFinished,
  reset: resetBubbles
} = useBubbles()

async function runTool(call: ToolCall) {
  if (call.name === 'web_search') {
    const args = JSON.parse(call.arguments || '{}') as { query?: string }
    return { output: await search(args.query ?? '', searchKey.value, store.grant?.sessionId ?? '') }
  }
  if (call.name === 'camera_snapshot') {
    const video = camPip.value?.video
    if (!camStream.value || !video?.videoWidth) return { output: 'The camera is not available right now.' }
    const image = snapshot(video)
    camPip.value?.flash()
    return image ? { output: 'Here is the current camera frame.', image } : { output: 'The camera is not available right now.' }
  }
  return { output: `Unknown tool: ${call.name}` }
}

/** 气泡只搬一句话；完整 Input/Output 由 `store.applyToolCall/Result` 落进历史条目。 */
function describeTool(call: ToolCallRecord): string {
  if (call.name === 'web_search') {
    try {
      const args = JSON.parse(call.arguments || '{}') as { query?: string }
      return `Searching for “${args.query ?? ''}”`
    } catch {
      return 'Searching the web'
    }
  }
  if (call.name === 'camera_snapshot') return 'Capturing a camera frame'
  return `Running ${call.name}`
}

async function connect(): Promise<void> {
  if (client) return
  store.resetTranscript()
  resetBubbles()
  micError.value = ''
  notice.value = ''
  queueFull.value = false
  try {
    mic = await acquireMic(store.settings.audioInputId)
  } catch (error: any) {
    micError.value = error?.code ?? 'mic-failed'
    store.setState('idle')
    return
  }
  client = new S2sClient({
    transport: store.config.rtc && store.settings.transport === 'webrtc' ? 'webrtc' : 'websocket',
    // 没有 LB 的部署不再请求 `/api/session`（那个接口在直连模式下是 404），
    // 而是直接 dial：钉死的地址优先，否则走同源 `/v1/realtime` 反代。
    allowDirect: store.config.allowDirect,
    directUrl: store.config.s2sUrl,
    sessionUrl: '/api/session',
    callsUrl: '/api/calls',
    voice: store.settings.voice,
    instructions: store.settings.instructions,
    tools: tools.value,
    iceServers: store.config.iceServers,
    startupGreeting: store.config.startupGreeting,
    localVad: store.settings.localVad,
    noiseGate: { enabled: store.settings.noiseGateDb > GATE_OFF_DB, thresholdDb: store.settings.noiseGateDb },
    playbackBufferMs: store.settings.playbackBufferMs,
    micStream: mic,
    acquireMic: () => Promise.resolve(mic as MediaStream),
    executeTool: runTool
  })
  client.addEventListener('status', (event: Event) => {
    const status = (event as CustomEvent).detail.status as VoiceStatus
    store.setState(status)
    // demo/main.js:1484：直接音频模型可能只有输出、没有转写，所以「开始说话」也算助手动静。
    if (status === 'ai-speaking') assistantActivity()
  })
  // 气泡与原音都听这四个事件（demo 客户端同名事件，main.js:1490-1501）。
  client.addEventListener('user-turn-started', (event: Event) =>
    userTurnStarted((event as CustomEvent<{ itemId?: string }>).detail.itemId)
  )
  client.addEventListener('user-turn-stopped', (event: Event) =>
    userTurnStopped((event as CustomEvent<{ itemId?: string }>).detail.itemId)
  )
  client.addEventListener('user-audio', (event: Event) => store.applyUserAudio((event as CustomEvent).detail as SentAudio))
  client.addEventListener('queue', (event: Event) => {
    // 排队位置与退队票据只能从这条事件里来（`acquireGrant` 的轮询回调）。
    // `pollIntervalS` 是 client 内部自己用的节奏，页面不读，填 0 只为满足票据形状。
    const detail = (event as CustomEvent).detail as { queueId: string; position: number }
    store.queue = { queueId: detail.queueId, position: detail.position, pollIntervalS: 0 }
  })
  client.addEventListener('server-event', (event: Event) => store.applyEvent((event as CustomEvent).detail))
  // 抽屉与气泡共用同一个累加器：store 把增量算成整句后广播，页面不再解析原始事件。
  store.subscribeTranscript((detail) => {
    if (detail.role === 'user') userTranscript({ itemId: detail.itemId, text: detail.text, partial: detail.partial })
    else assistantTranscript({ responseId: detail.responseId, text: detail.text })
  })
  client.addEventListener('tool-call', (event: Event) => {
    const call = (event as CustomEvent).detail as ToolCallRecord
    store.applyToolCall(call)
    showToolBubble(describeTool(call))
  })
  client.addEventListener('tool-result', (event: Event) => {
    store.applyToolResult((event as CustomEvent).detail as ToolResultRecord)
  })
  client.addEventListener('level', (event: Event) => {
    const db = (event as CustomEvent).detail.db as number
    levelDb.value = db
    detector.push(db)
  })
  client.addEventListener('session', (event: Event) => {
    const grant = (event as CustomEvent).detail.grant
    if (!grant?.sessionId) return
    store.grant = grant
    // 已经拿到会话：票据作废，否则 `leaveQueue` 会对一个已消费的 id 发 beacon。
    store.queue = null
    if (grant.remainingSec != null) store.me = { ...store.me, remainingSec: grant.remainingSec }
    void client?.setAudioOutputDevice(store.settings.audioOutputId)
    startHeartbeat(grant.heartbeatSec)
    void refreshMe()
  })
  client.addEventListener('ready-to-join', (event: Event) => {
    expiresSec.value = (event as CustomEvent).detail.expiresSec ?? 60
  })
  client.addEventListener('response-finished', (event: Event) => {
    const detail = (event as CustomEvent).detail as {
      responseId?: string
      status?: string
      transcript?: string
      latency?: TurnLatency | null
    }
    // 被打断的回复先补回历史行，再挂计时：补建的那一行才是本轮的归属（demo chat.js:619-624）。
    if (detail.status === 'cancelled') store.markInterrupted(detail.responseId ?? '', detail.transcript ?? '')
    // §3.9.4：计时交给 store 挂到那条助手条目上（demo 的 `_appendTimings` 也挂在 hist 条目里）。
    // 页面自己不再持有 `turnIndex` / `store.latency` ——历史抽屉里每条助手条目各有一份数字，
    // 只存「最新一条」会让同一条对话在抽屉里除了最后一句之外全部没有计时。
    store.attachLatency(detail.latency ?? null)
    // 气泡不跟着 `response.done` 立即消失：demo 只在这里释放 `response_id` 映射，
    // 气泡按自己的计时淡出（chat.js:629-633）。
    responseFinished(detail)
  })
  try {
    await client.connect()
  } catch (error: any) {
    // 402 / 401 / queue-full / join-expired 都以带 code 的错误到达。
    notice.value = CONNECT_ERRORS[error?.code] ?? 'Could not start the conversation.'
    queueFull.value = error?.code === 'queue-full'
    if (error?.code === 'limit') limitOpen.value = true
    await teardown()
    store.setState('error')
    return
  }
  if (store.settings.localVad) {
    vad = await startLocalVad({
      stream: mic,
      isEnabled: () => Boolean(client),
      // 本地 VAD 只是「比服务端早一拍」的提示：它能把自己推成 user-speaking，
      // 但不能把 `ai-speaking` / `processing` 这些真相覆盖回去。
      onChange: (speaking) => {
        if (speaking) store.setState('user-speaking')
        else if (store.state === 'user-speaking') store.setState('listening')
      }
    })
  }
  if (store.settings.tools.camera) await startCamera()
}

function startHeartbeat(seconds: number | null): void {
  stopHeartbeat()
  if (!seconds) return
  heartbeatTimer = window.setInterval(async () => {
    const sessionId = store.grant?.sessionId
    if (!sessionId) return
    const result = await heartbeat(sessionId)
    if (result.remainingSec != null) store.me = { ...store.me, remainingSec: result.remainingSec }
    // 额度中途用完：立刻拆掉并弹限制卡，不等下一次 402。
    if (result.expired) {
      limitOpen.value = true
      await stop()
    }
  }, seconds * 1000)
}

function stopHeartbeat(): void {
  if (heartbeatTimer) window.clearInterval(heartbeatTimer)
  heartbeatTimer = 0
}

async function teardown(): Promise<void> {
  stopHeartbeat()
  await vad?.destroy()
  vad = null
  await client?.close()
  client = null
  // 气泡不跨越一次通话：挂断后屏幕上不该残留上一轮的占位与文字。
  store.subscribeTranscript(null)
  resetBubbles()
  releaseMic(mic)
  mic = null
  stopCamera()
  detector.reset()
  levelDb.value = -100
}

async function stop(): Promise<void> {
  if (store.grant?.sessionId) endSessionBeacon(store.grant.sessionId)
  store.grant = null
  await teardown()
  store.setState('idle')
  notice.value = ''
  micError.value = ''
}

/** 「Restart conversation with these settings」：丢会话、带新设置重连。 */
async function restart(): Promise<void> {
  await stop()
  await connect()
}

async function leaveQueue(): Promise<void> {
  const queueId = store.queue?.queueId
  if (queueId) leaveQueueBeacon(queueId)
  store.queue = null
  queueFull.value = false
  await stop()
}

function join(): void {
  client?.join()
}

function toggleMute(next: boolean): void {
  muted.value = next
  client?.setMuted(next)
}

function setGate(db: number): void {
  store.saveSettings({ ...store.settings, noiseGateDb: db })
  client?.setNoiseGate({ enabled: db > GATE_OFF_DB, thresholdDb: db })
}

async function startCamera(): Promise<void> {
  if (camStream.value) return
  try {
    camStream.value = await openCamera()
    // PiP 是 v-if 挂上的：等它真的在 DOM 里再 srcObject，否则拿到 null。
    await nextTick()
    const video = camPip.value?.video
    if (video) {
      video.srcObject = camStream.value
      await video.play().catch(() => {})
    }
  } catch {
    stopCamera()
    store.saveSettings({ ...store.settings, tools: { ...store.settings.tools, camera: false } })
  }
}

function stopCamera(): void {
  for (const track of camStream.value?.getTracks() ?? []) track.stop()
  camStream.value = null
  const video = camPip.value?.video
  if (video) video.srcObject = null
}

async function applySession(instructions: string): Promise<void> {
  if (!client) return
  client.updateSession({ instructions })
}

async function refreshDevices(): Promise<void> {
  if (!navigator.mediaDevices?.enumerateDevices) return
  const devices = await navigator.mediaDevices.enumerateDevices()
  inputs.value = devices
    .filter((device) => device.kind === 'audioinput')
    .map((device, index) => ({ id: device.deviceId, label: device.label || `Microphone ${index + 1}` }))
  outputs.value = devices
    .filter((device) => device.kind === 'audiooutput')
    .map((device, index) => ({ id: device.deviceId, label: device.label || `Speakers ${index + 1}` }))
}

async function onSettingsSave(next: VoiceSettings): Promise<void> {
  store.saveSettings(next)
  // 工具、门限、输出设备立即生效；其余按 demo 的规矩等下一个会话（或 Restart）。
  client?.setTools(tools.value)
  client?.setNoiseGate({ enabled: next.noiseGateDb > GATE_OFF_DB, thresholdDb: next.noiseGateDb })
  await client?.setAudioOutputDevice(next.audioOutputId)
  await applySession(next.instructions)
  if (next.tools.camera) await startCamera()
  else stopCamera()
}

function onToolsChange(): void {
  store.saveSettings(store.settings)
  client?.setTools(tools.value)
  if (store.settings.tools.camera) void startCamera()
  else stopCamera()
}

async function refreshMe(): Promise<void> {
  store.me = await getMe()
}

onMounted(async () => {
  store.config = await getDemoConfig()
  store.loadSettings()
  void refreshMe()
  void refreshDevices()
})

onBeforeUnmount(() => {
  // 页面卸载必须退回预约：sendBeacon 能在 unload 之后仍送达。
  if (store.grant?.sessionId) endSessionBeacon(store.grant.sessionId)
  if (store.queue?.queueId) leaveQueueBeacon(store.queue.queueId)
  stopHeartbeat()
  void teardown()
})
</script>

<template>
  <main class="v-page">
    <!-- 顶栏的账号 chip 与工具 / 历史 / 设置三枚按钮由外壳（`ConsoleLayout`）直接渲染；
         侧栏/顶栏动作经 `shell.voiceOverlay` / `shell.limitOpen` 通知本页开浮层。 -->

    <!-- 标题与 blurb 退回舞台头部：外壳顶栏已经被品牌与账号占据（§3.2.4）。 -->
    <header class="v-head">
      <IdentityBlock />
    </header>

    <section class="v-stage">
      <BubbleStack :items="bubbleItems" />

      <OrbStage
        :state="store.state"
        :level-db="levelDb"
        :caption="caption"
        :sub-caption="subCaption"
        :tone="captionTone"
        @activate="connect"
      >
        <template #left>
          <MicGate v-if="store.live" :muted="muted" :gate-db="store.settings.noiseGateDb" :level-db="levelDb" @update:muted="toggleMute" @update:gate-db="setGate" />
        </template>
        <template #right>
          <button v-if="store.live" class="v-side v-side--stop" type="button" aria-label="End" title="End" @click="stop">
            <svg class="v-i v-i--fill" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-stop" /></svg>
          </button>
        </template>
      </OrbStage>

      <QueueOverlay
        :state="store.state"
        :position="store.queue?.position ?? 0"
        :expires-sec="expiresSec"
        :full="queueFull"
        @join="join"
        @leave="leaveQueue"
      />

      <!--
        舞台上不放任何计时 chip：demo 的 `index.html` / `main.js` 搜不到 latency 节点，
        计时只出现在历史条目的 `details.hist-timings` 里（`TranscriptList` → `TurnTimings`）。
        这里也不再传 `turnIndex`：没有任何组件需要它。
      -->
    </section>



    <CameraPip ref="camPip" :active="store.settings.tools.camera && Boolean(camStream)" />

    <HistoryDrawer
      v-if="store.historyOpen"
      :open="store.historyOpen"
      :entries="store.entries"
      @replay="onReplay"
      @update:open="(value: boolean) => (value ? store.openHistory() : store.closeHistory())"
    />

    <SettingsDialog
      v-if="settingsOpen"
      v-model:open="settingsOpen"
      :server-url="serverUrl"
      :mode="store.config.allowDirect ? 'direct' : 'load-balancer'"
      :pipeline="store.config.pipeline"
      :transport-locked="transportLocked"
      :rtc-available="rtcAvailable"
      :voices="VOICES"
      :inputs="inputs"
      :outputs="outputs"
      :settings="store.settings"
      :connected="store.live"
      @save="onSettingsSave"
      @restart="restart"
    />

    <ToolsDialog
      v-if="toolsOpen"
      v-model:open="toolsOpen"
      :search-available="searchAvailable"
      :server-key="serverKey"
      :web-search="store.settings.tools.web"
      :camera="store.settings.tools.camera"
      :search-key="searchKey"
      @update:web-search="(value: boolean) => { store.settings.tools.web = value; onToolsChange() }"
      @update:camera="(value: boolean) => { store.settings.tools.camera = value; onToolsChange() }"
      @update:search-key="(value: string) => { searchKey = value; onToolsChange() }"
    />

    <LimitDialog v-if="limitOpen" v-model:open="limitOpen" v-bind="limitCopy" />
  </main>
</template>
