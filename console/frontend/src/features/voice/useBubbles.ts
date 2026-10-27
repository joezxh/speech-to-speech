import { ref } from 'vue'

import type { Bubble } from './types'

/**
 * 舞台上那叠一闪而过的气泡——`demo/ui/chat.js` 的临时层。
 *
 * demo 用命令式 DOM + WeakMap 做到四件事，这里用 Vue 的响应式数组做同样的事：
 * 1. 一个 item 只有一个活动气泡，增量在原位改写，不新增（`_updateBubbleText`）；
 * 2. 到期时间挂在**每条气泡**上，每次更新往后推（`_bumpDismiss`）——所以一直说话的用户
 *    气泡不会走，安静几秒才走；
 * 3. 只有一个定时器，清理严格从最旧那条开始，遇到还活着的就停（`_reapBubbles`）——
 *    不会出现最新的气泡先消失；
 * 4. 超过 3 条时，撤的是除「调用方还在更新的」之外最旧的那条（`_spawnBubble`）。
 */

/** demo `_spawnBubble` 的栈深上限。 */
const MAX_VISIBLE = 3
/** demo `onUserTurnStarted` 的 fail-safe：`speech_stopped` 丢了也不会永远挂着。 */
const TURN_FAILSAFE_MS = 30_000
/** demo `onUserTurnStopped` / 用户转写的停留时间。 */
const TURN_STOP_MS = 6_000
/** demo `_bumpDismiss` 的默认值：助手回答与工具调用。 */
const DEFAULT_DISMISS_MS = 4_000

export interface UserTranscript {
  itemId?: string
  text: string
  /**
   * 抽屉需要它（partial 的行有 `is-partial`），气泡不需要：demo 的 `_updateBubbleText`
   * 对增量和终稿做同样的事，这里也就不区分——保留参数只为了让调用方不必分两条路径。
   */
  partial: boolean
}

export interface AssistantTranscript {
  responseId?: string
  text: string
}

/** `response.done` 里气泡唯一需要的两个字段（demo 的 `onResponseFinished`）。 */
export interface ResponseClosing {
  responseId?: string
  status?: string
}

export function useBubbles() {
  const items = ref<Bubble[]>([])

  /** 每条气泡的到期时刻（epoch ms），等价于 demo 的 `_bubbleExpiry`。 */
  const expiry = new Map<number, number>()
  /** `response_id` → 气泡 id，等价于 demo 的 `_asstByResp`（这里只关心气泡那一半）。 */
  const asstByResp = new Map<string, number>()

  let seq = 0
  /** 服务端没给 id 时的兜底计数，保证无主的消息不会叠到同一条上。 */
  let anonSeq = 0
  let activeUserId = ''
  let activeId = 0
  /**
   * 媒体事件与 data-channel 事件之间没有先后保证：助手已经开始答了，
   * 迟到的 `speech_stopped` 就不能再把这一轮画成「正在发送语音」。
   */
  let dismissedUserId = ''
  // 只有一个待醒的定时器：清理顺序由 `_reapBubbles` 的栈序保证，不靠每个气泡各报一个。
  let reaperHandle: ReturnType<typeof setTimeout> | undefined

  function isLive(id: number): boolean {
    return items.value.some((item) => item.id === id)
  }

  function find(id: number): Bubble | undefined {
    return items.value.find((item) => item.id === id)
  }

  function dismiss(id: number): void {
    if (!isLive(id)) return // 幂等：demo 的 `.out` 短路
    expiry.delete(id)
    items.value = items.value.filter((item) => item.id !== id)
    if (id === activeId) activeId = 0
  }

  /**
   * 栈顶（最旧）那条的到期时刻决定唯一定时器什么时候醒。
   * 到期时间变早和变晚都必须重排：listening 的 30s fail-safe 会在语音结束后缩成 6s。
   */
  function scheduleReaper(): void {
    if (reaperHandle !== undefined) clearTimeout(reaperHandle)
    reaperHandle = undefined
    const oldest = items.value[0]
    if (!oldest) return
    const at = expiry.get(oldest.id) ?? Date.now()
    reaperHandle = setTimeout(() => reap(), Math.max(50, at - Date.now()))
  }

  /**
   * 到期的淡掉——严格按栈序从最旧开始：走到第一条还活着就停下，
   * 后面的再老也不许先于前面的离开。
   */
  function reap(): void {
    reaperHandle = undefined
    const now = Date.now()
    let nextWake = Number.POSITIVE_INFINITY
    for (const item of items.value) {
      const at = expiry.get(item.id) ?? now // 没记到期时间就当到时间了
      if (at <= now) dismiss(item.id)
      else {
        nextWake = at
        break
      }
    }
    if (nextWake !== Number.POSITIVE_INFINITY) {
      reaperHandle = setTimeout(() => reap(), Math.max(50, nextWake - Date.now()))
    }
  }

  /** 重设到期时间：还在更新的气泡就一直留在屏幕上。 */
  function bump(id: number, delay = DEFAULT_DISMISS_MS): void {
    expiry.set(id, Date.now() + delay)
    scheduleReaper()
  }

  function spawn(role: Bubble['role'], text: string, voice = false, voiceState: Bubble['voiceState'] = null): Bubble {
    const item: Bubble = { id: ++seq, role, text, voice, voiceState }
    items.value = [...items.value, item]
    // 封顶 3 条，但绝不先撤调用方还在更新的这条，撤的是剩下的里最旧的。
    if (items.value.length > MAX_VISIBLE) {
      const victim = items.value.find((bubble) => bubble.id !== activeId) ?? items.value[0]
      dismiss(victim.id)
    }
    return item
  }

  /** 文本落进气泡，语音占位的形态就地卸掉（demo 的 `_updateBubbleText`）。 */
  function setText(id: number, text: string): void {
    items.value = items.value.map((item) => (item.id === id ? { ...item, text, voice: false, voiceState: null } : item))
  }

  function setVoiceState(id: number, state: Bubble['voiceState']): void {
    items.value = items.value.map((item) => (item.id === id ? { ...item, voiceState: state } : item))
  }

  /** 语音占位气泡：转写还没到，先占住这一条，免得后面补出第二条用户消息。 */
  function spawnVoice(state: Bubble['voiceState']): Bubble {
    return spawn('user', '', true, state)
  }

  function userTurnStarted(itemId?: string): void {
    const id = itemId || `_u${++anonSeq}`
    // 投机续接会复用没走完的 item：新的开始要覆盖掉之前的墓碑。
    dismissedUserId = ''
    const reusable = activeUserId === id && activeId !== 0 && isLive(activeId)
    if (!reusable) {
      const active = activeId ? find(activeId) : undefined
      if (active?.voice) dismiss(active.id)
      const item = spawnVoice('listening')
      activeId = item.id
      activeUserId = id
    } else if (find(activeId)?.voice) {
      setVoiceState(activeId, 'listening')
    }
    bump(activeId, TURN_FAILSAFE_MS)
  }

  /** 闭麦之后、这一轮发出去之前：占位气泡换成「正在发送语音」。 */
  function userTurnStopped(itemId?: string): void {
    const id = itemId || activeUserId || `_u${++anonSeq}`
    const reusable = activeUserId === id && activeId !== 0 && isLive(activeId)
    if (!reusable && dismissedUserId === id) return
    if (!reusable) {
      const item = spawnVoice('sending')
      activeId = item.id
      activeUserId = id
    } else if (find(activeId)?.voice) {
      setVoiceState(activeId, 'sending')
    }
    bump(activeId, TURN_STOP_MS)
  }

  /**
   * 用户转写增量。纯计时驱动：每个增量刷新到期时间，说完几秒后自己走，
   * 不依赖回复是否到达，所以永远不会卡住。
   */
  function userTranscript(transcript: UserTranscript): void {
    const id = transcript.itemId || activeUserId || `_u${++anonSeq}`
    if (activeUserId !== id || activeId === 0 || !isLive(activeId)) {
      const item = spawn('user', transcript.text)
      activeId = item.id
      activeUserId = id
    } else {
      setText(activeId, transcript.text)
    }
    bump(activeId, TURN_STOP_MS)
  }

  /** 助手转写按 `response_id` 归组：同一个回复的多次更新落在同一条气泡上。 */
  function assistantTranscript(transcript: AssistantTranscript): void {
    assistantActivity()
    const rid = transcript.responseId || `_a${++anonSeq}`
    const mappedId = asstByResp.get(rid)
    if (mappedId === undefined) {
      const item = spawn('assistant', transcript.text)
      asstByResp.set(rid, item.id)
      bump(item.id)
      return
    }
    setText(mappedId, transcript.text)
    bump(mappedId)
  }

  /** 模型正在跑工具：只给一个短暂气泡，完整的 Input/Output 归抽屉。 */
  function toolCall(name: string): void {
    bump(spawn('tool', name).id)
  }

  /**
   * 助手已经明显开始答了：撤掉还挂着的语音占位气泡。
   * 转写到达和音频开始播放都会走这里——直接音频模型可能只有后者。
   */
  function assistantActivity(): void {
    const active = activeId ? find(activeId) : undefined
    if (!active || !active.voice) return
    dismissedUserId = activeUserId
    dismiss(active.id)
    scheduleReaper()
  }

  /** 回复关闭（完成或取消）：释放映射，气泡按自己的计时淡出。 */
  function responseFinished(closing: ResponseClosing): void {
    assistantActivity()
    if (!closing.responseId) return
    asstByResp.delete(closing.responseId)
  }

  /** 挂断或重开：清干净气泡和所有计时，不留跨通话的状态。 */
  function reset(): void {
    if (reaperHandle !== undefined) clearTimeout(reaperHandle)
    reaperHandle = undefined
    items.value = []
    expiry.clear()
    asstByResp.clear()
    activeUserId = ''
    activeId = 0
    dismissedUserId = ''
  }

  return {
    items,
    userTurnStarted,
    userTurnStopped,
    userTranscript,
    assistantTranscript,
    toolCall,
    assistantActivity,
    responseFinished,
    reset
  }
}
