import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useBubbles } from './useBubbles'

// 语义基准：demo/ui/chat.js 的临时气泡层。四条规则互相咬合，缺一不可：
//   1. 一个 item 只有一个活动气泡，partial 增量原位改写它（`_updateBubbleText`）；
//   2. 每条气泡有自己的到期时间，每次更新重排（`_bumpDismiss`）；
//   3. 清理只按栈序从最旧开始，最旧的还活着就不许撤更新的（`_reapBubbles`）；
//   4. 同时最多 3 条可见，且撤的时候跳过调用方还在更新的的那条（`_spawnBubble`）。

/** 把整条链路推进 `ms` 毫秒：定时器与 Date.now 一起走。 */
function advance(ms: number): void {
  vi.advanceTimersByTime(ms)
}

beforeEach(() => {
  vi.useFakeTimers()
})

describe('useBubbles', () => {
  it('rewrites the same bubble for every partial delta of one item', () => {
    const stack = useBubbles()
    stack.userTranscript({ itemId: 'i1', text: '你', partial: true })
    stack.userTranscript({ itemId: 'i1', text: '你好', partial: true })
    stack.userTranscript({ itemId: 'i1', text: '你好吗', partial: false })
    expect(stack.items.value).toHaveLength(1)
    expect(stack.items.value[0]).toMatchObject({ role: 'user', text: '你好吗', voice: false })
  })

  it('drops the previous voice placeholder when a new item starts', () => {
    const stack = useBubbles()
    stack.userTurnStarted('i1')
    expect(stack.items.value).toHaveLength(1)
    const firstId = stack.items.value[0].id
    stack.userTurnStarted('i2')
    expect(stack.items.value.find((bubble) => bubble.id === firstId)).toBeUndefined()
    expect(stack.items.value).toHaveLength(1)
    expect(stack.items.value[0].voice).toBe(true)
  })

  it('keeps the voice placeholder until the 30s fail-safe', () => {
    const stack = useBubbles()
    stack.userTurnStarted('i1')
    advance(10_000)
    expect(stack.items.value).toHaveLength(1)
    expect(stack.items.value[0]).toMatchObject({ voice: true, voiceState: 'listening' })
    advance(25_000)
    expect(stack.items.value).toHaveLength(0)
  })

  it('turns the placeholder into the transcript bubble in place', () => {
    const stack = useBubbles()
    stack.userTurnStarted('i1')
    const placeholderId = stack.items.value[0].id
    stack.userTranscript({ itemId: 'i1', text: '你好', partial: true })
    expect(stack.items.value).toHaveLength(1)
    expect(stack.items.value[0].id).toBe(placeholderId)
    expect(stack.items.value[0]).toMatchObject({ voice: false, voiceState: null, text: '你好' })
  })

  it('switches the placeholder to sending once the turn closes', () => {
    const stack = useBubbles()
    stack.userTurnStarted('i1')
    stack.userTurnStopped('i1')
    expect(stack.items.value[0]).toMatchObject({ voice: true, voiceState: 'sending' })
    // sending 状态只留 6s：比 listening 的 30s fail-safe 短得多。
    advance(7_000)
    expect(stack.items.value).toHaveLength(0)
  })

  it('does not rebuild a placeholder that assistant activity already dismissed', () => {
    const stack = useBubbles()
    stack.userTurnStarted('i1')
    stack.assistantActivity()
    expect(stack.items.value).toHaveLength(0)
    // RTC 的媒体事件与 data-channel 事件没有先后保证：迟到的 speech_stopped
    // 不能把已经答完的这一轮重新画成「正在发送语音」。
    stack.userTurnStopped('i1')
    expect(stack.items.value).toHaveLength(0)
    // 新的一轮仍然要能正常起气泡。
    stack.userTurnStarted('i2')
    expect(stack.items.value).toHaveLength(1)
  })

  it('caps the stack at three bubbles and never evicts the live one first', () => {
    const stack = useBubbles()
    // 还在跳增量的用户气泡（demo 的 `_activeUserBubble`）就是「调用方还在更新的那条」。
    stack.userTranscript({ itemId: 'i1', text: '我还在说', partial: true })
    stack.assistantTranscript({ responseId: 'r1', text: '一' })
    stack.assistantTranscript({ responseId: 'r2', text: '二' })
    stack.assistantTranscript({ responseId: 'r3', text: '三' })
    expect(stack.items.value).toHaveLength(3)
    // 被撤的是最旧的那条助手气泡，不是还在更新的用户气泡。
    expect(stack.items.value[0]).toMatchObject({ role: 'user', text: '我还在说' })
    expect(stack.items.value.some((bubble) => bubble.text === '一')).toBe(false)
  })

  it('reaps strictly oldest-first', () => {
    const stack = useBubbles()
    stack.assistantTranscript({ responseId: 'r1', text: '旧' })
    advance(3_000)
    stack.assistantTranscript({ responseId: 'r2', text: '新' })
    // r1 的 4s 到期在 r2 之后才轮到：最旧的没走，最新的必须留下。
    advance(1_500)
    expect(stack.items.value.map((bubble) => bubble.text)).toEqual(['新'])
    advance(3_000)
    expect(stack.items.value).toHaveLength(0)
  })

  it('releases the response mapping when a response finishes', () => {
    const stack = useBubbles()
    stack.userTurnStarted('i1')
    stack.assistantTranscript({ responseId: 'r1', text: '答' })
    // 助手转写本身就算助手活动：语音占位气泡已经让位了。
    expect(stack.items.value.map((bubble) => bubble.text)).toEqual(['答'])
    stack.responseFinished({ responseId: 'r1', status: 'cancelled' })
    // demo 不因为取消而立即撤掉助手气泡（它有自己的计时器），只释放 responseId 映射：
    // 同一个 id 重开时是一条新气泡，而不是覆写旧的那条。
    stack.assistantTranscript({ responseId: 'r1', text: '重开' })
    expect(stack.items.value.some((bubble) => bubble.text === '答')).toBe(true)
    expect(stack.items.value.some((bubble) => bubble.text === '重开')).toBe(true)
  })

  it('shows a tool bubble with the call name', () => {
    const stack = useBubbles()
    stack.toolCall('web_search')
    expect(stack.items.value[0]).toMatchObject({ role: 'tool', text: 'web_search', voice: false })
    advance(4_500)
    expect(stack.items.value).toHaveLength(0)
  })

  it('starts clean on reset', () => {
    const stack = useBubbles()
    stack.userTranscript({ itemId: 'i1', text: '你好', partial: false })
    stack.assistantTranscript({ responseId: 'r1', text: '在' })
    stack.reset()
    expect(stack.items.value).toHaveLength(0)
  })
})
