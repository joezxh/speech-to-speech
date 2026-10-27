import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { DEFAULT_SETTINGS, SETTINGS_KEY, useVoiceStore } from './voice'

function installStorage(): Map<string, string> {
  const data = new Map<string, string>()
  ;(globalThis as any).localStorage = {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
    clear: () => data.clear()
  }
  return data
}

beforeEach(() => {
  installStorage()
  setActivePinia(createPinia())
})

describe('voice store', () => {
  it('paints `connected` as `listening` — the orb has no separate connected face', () => {
    const store = useVoiceStore()
    store.setState('connected')
    expect(store.state).toBe('listening')
    expect(store.live).toBe(true)
  })

  it('keeps the transcript in arrival order and replaces the array so Vue re-renders', () => {
    const store = useVoiceStore()
    store.applyEvent({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: 'hi' })
    store.applyEvent({ type: 'response.audio_transcript.done', response_id: 'r1', transcript: 'hello' })

    expect(store.entries.map((e) => e.role)).toEqual(['user', 'assistant'])
  })

  it('hands the server timings to the last assistant entry, not to a global slot', () => {
    const store = useVoiceStore()
    store.applyEvent({ type: 'response.audio_transcript.done', response_id: 'r1', transcript: 'hello' })
    store.attachLatency({
      version: 2,
      turn_id: 't1',
      turn_revision: 0,
      response_key: 'r1',
      status: 'completed',
      stt_s: 0.12,
      llm_s: null,
      tts_ttfa_s: 0.05,
      e2e_s: 0.51,
      vad_decision_s: 0.55,
      smart_status: 'disabled',
      hold_s: null
    })

    const last = store.entries[store.entries.length - 1]
    expect(last?.latency?.e2e_s).toBe(0.51)
    // 下一条回复到达之前的 `null` 不得把已挂上的数字抹掉（demo 每条 hist 各留一份）。
    store.attachLatency(null)
    expect(store.entries[store.entries.length - 1]?.latency?.e2e_s).toBe(0.51)
  })

  it('persists the settings demo keeps in localStorage', () => {
    const store = useVoiceStore()
    store.saveSettings({ ...DEFAULT_SETTINGS, voice: 'Serena', noiseGateDb: -42 })

    const raw = (globalThis as any).localStorage.getItem(SETTINGS_KEY) ?? ''
    expect(JSON.parse(raw).voice).toBe('Serena')
    expect(raw).not.toContain('searchKey')
  })

  it('loads saved settings and falls back per missing field', () => {
    (globalThis as any).localStorage.setItem(SETTINGS_KEY, JSON.stringify({ voice: 'Vivian' }))

    const store = useVoiceStore()
    store.loadSettings()

    expect(store.settings.voice).toBe('Vivian')
    expect(store.settings.playbackBufferMs).toBe(DEFAULT_SETTINGS.playbackBufferMs)
    expect(store.settings.tools.camera).toBe(false)
  })

  it('survives a corrupt settings record instead of failing to mount', () => {
    (globalThis as any).localStorage.setItem(SETTINGS_KEY, '{not json')

    const store = useVoiceStore()
    expect(() => store.loadSettings()).not.toThrow()
    expect(store.settings).toEqual(DEFAULT_SETTINGS)
  })

  it('keeps the transcript out of storage — a refresh ends the conversation, as in demo', () => {
    const store = useVoiceStore()
    store.applyEvent({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: 'hi' })
    store.saveSettings(store.settings)

    const raw = (globalThis as any).localStorage.getItem(SETTINGS_KEY) ?? ''
    expect(raw).not.toContain('hi')
    expect(Object.keys(JSON.parse(raw))).not.toContain('entries')
  })

  it('ignores transport states the orb cannot paint, instead of blanking the indicator', () => {
    const store = useVoiceStore()
    store.setState('listening')
    store.setState('creating-session' as never)
    store.setState('closed')

    expect(store.state).toBe('listening')
  })

  it('shows a tool call as one entry, then fills its Output from the result', () => {
    const store = useVoiceStore()
    store.applyToolCall({ name: 'web_search', arguments: '{"query":"paris"}', callId: 'c1' })

    expect(store.entries).toHaveLength(1)
    expect(store.entries[0]?.role).toBe('tool')
    expect(store.entries[0]?.partial).toBe(true)
    expect(store.entries[0]?.tool?.input).toContain('"query": "paris"')
    expect(store.entries[0]?.tool?.output).toBe('')

    store.applyToolResult({ name: 'web_search', arguments: '{"query":"paris"}', callId: 'c1', output: '18°C' })

    // 同一个 callId 只替换，不追加第二条。
    expect(store.entries).toHaveLength(1)
    expect(store.entries[0]?.partial).toBe(false)
    expect(store.entries[0]?.tool?.output).toBe('18°C')
  })

  it('still renders a camera snapshot whose result carries an image', () => {
    const store = useVoiceStore()
    store.applyToolCall({ name: 'camera_snapshot', arguments: '{}', callId: 'c9' })
    store.applyToolResult({ name: 'camera_snapshot', arguments: '{}', callId: 'c9', output: 'frame', image: 'data:image/png;base64,AA' })

    expect(store.entries[0]?.tool?.image).toBe('data:image/png;base64,AA')
  })

  // 抽屉里「播放我发给模型的原音」：object URL 的生杀全在 store 手里，
  // 因为条目会被替换而不是就地修改（demo 用 `_audioUrls` + `revokeObjectURL` 做同一件事）。
  describe('user audio', () => {
    let created: string[]
    let revoked: string[]

    beforeEach(() => {
      created = []
      revoked = []
      ;(globalThis.URL as any).createObjectURL = vi.fn(() => {
        const url = `blob:${created.length + 1}`
        created.push(url)
        return url
      })
      ;(globalThis.URL as any).revokeObjectURL = vi.fn((url: string) => revoked.push(url))
    })

    function recording(itemId = 'i1') {
      return { itemId, blob: new Blob(['wav'], { type: 'audio/wav' }), durationMs: 1500, truncated: false }
    }

    it('turns a recording into a playable entry', () => {
      const store = useVoiceStore()
      store.applyUserAudio(recording())

      expect(store.entries).toHaveLength(1)
      expect(store.entries[0]).toMatchObject({ role: 'user', key: 'u:i1', audio: { url: 'blob:1', durationMs: 1500 } })
    })

    it('revoke the superseded url when a continuation replaces it', () => {
      const store = useVoiceStore()
      store.applyUserAudio(recording())
      store.applyUserAudio(recording())

      expect(store.entries).toHaveLength(1)
      expect(revoked).toEqual(['blob:1'])
      expect(store.entries[0]?.audio?.url).toBe('blob:2')
    })

    it('revokes every url when the transcript is reset for a new call', () => {
      const store = useVoiceStore()
      store.applyUserAudio(recording('i1'))
      store.applyUserAudio(recording('i2'))
      store.resetTranscript()

      expect(store.entries).toHaveLength(0)
      expect(revoked.sort()).toEqual(['blob:1', 'blob:2'])
    })

    it('keeps the audio when the transcript for the same item lands afterwards', () => {
      const store = useVoiceStore()
      store.applyUserAudio(recording('i1'))
      store.applyEvent({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: 'hi' })

      expect(store.entries).toHaveLength(1)
      expect(store.entries[0]).toMatchObject({ text: 'hi', audio: { url: 'blob:1' } })
    })
  })

  // 气泡要的是「每一次更新」，而不是最终列表（demo 客户端的 `transcript` 事件）。
  // store 已经把累加做完了，只需把这一步同样的信息递出去，不让页面再解析一遍原始事件。
  describe('subscribeTranscript', () => {
    it('reports every user and assistant update to the single listener', () => {
      const store = useVoiceStore()
      const seen: unknown[] = []
      store.subscribeTranscript((detail) => seen.push(detail))

      store.applyEvent({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'i1', delta: 'hel' })
      store.applyEvent({ type: 'response.audio_transcript.delta', response_id: 'r1', delta: 'Hi' })

      expect(seen).toEqual([
        { role: 'user', text: 'hel', partial: true, itemId: 'i1', responseId: '' },
        { role: 'assistant', text: 'Hi', partial: true, itemId: '', responseId: 'r1' }
      ])
    })

    it('stops reporting after the page unregisters the listener', () => {
      const store = useVoiceStore()
      const seen: unknown[] = []
      store.subscribeTranscript((detail) => seen.push(detail))
      store.subscribeTranscript(null)
      store.applyEvent({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: 'hi' })

      expect(seen).toEqual([])
      // 抽屉不依赖这个回调：取消订阅后转写照常记账。
      expect(store.entries.map((entry) => entry.text)).toEqual(['hi'])
    })
  })

  // 顶栏徽标不是「有内容就一直亮」：抽屉开着时新内容只算「已经看见了」，
  // 只有关闭期间来的东西才点亮，点开即清（demo chat.js:116-122 `_markUnread`、
  // chat.js:93-98 `_openPanel`）。开合状态必须由 store 持有，因为徽标在外壳、抽屉在页面。
  describe('unread badge', () => {
    function spoken(store: ReturnType<typeof useVoiceStore>, transcript = 'hi') {
      store.applyEvent({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript })
    }

    it('lights up when new content arrives while the drawer is closed', () => {
      const store = useVoiceStore()
      expect(store.historyOpen).toBe(false)
      spoken(store)

      expect(store.unread).toBe(true)
    })

    it('stays dark while the drawer is open, and lights up again after it closes', () => {
      const store = useVoiceStore()
      store.openHistory()
      spoken(store, 'first')
      expect(store.unread).toBe(false)

      store.closeHistory()
      spoken(store, 'second')
      expect(store.unread).toBe(true)
    })

    it('clears the badge the moment the drawer opens', () => {
      const store = useVoiceStore()
      spoken(store)
      store.openHistory()

      expect(store.historyOpen).toBe(true)
      expect(store.unread).toBe(false)
    })

    it('counts tool rows and server timings as new content too', () => {
      const store = useVoiceStore()
      store.applyToolCall({ name: 'web_search', arguments: '{}', callId: 'c1' })
      expect(store.unread).toBe(true)

      store.resetTranscript()
      store.applyEvent({ type: 'response.audio_transcript.done', response_id: 'r1', transcript: 'hello' })
      store.openHistory()
      store.attachLatency({
        version: 2,
        turn_id: 't1',
        turn_revision: 0,
        response_key: 'r1',
        status: 'completed',
        stt_s: 0.1,
        llm_s: null,
        tts_ttfa_s: 0.1,
        e2e_s: 0.5,
        vad_decision_s: null,
        smart_status: 'disabled',
        hold_s: null
      })
      expect(store.unread).toBe(false)

      store.closeHistory()
      store.attachLatency({
        version: 2,
        turn_id: 't2',
        turn_revision: 0,
        response_key: 'r1',
        status: 'completed',
        stt_s: 0.1,
        llm_s: null,
        tts_ttfa_s: 0.1,
        e2e_s: 0.6,
        vad_decision_s: null,
        smart_status: 'disabled',
        hold_s: null
      })
      expect(store.unread).toBe(true)
    })

    it('starts a new call with nothing unread', () => {
      const store = useVoiceStore()
      spoken(store)
      store.resetTranscript()

      expect(store.unread).toBe(false)
    })

    // demo 的 `#chat-btn` 是开合切换（chat.js:83），不是只会打开；顶栏那枚图标
    // 已经处于打开状态时再点应关抽屉。
    it('toggles the drawer from the top-bar button', () => {
      const store = useVoiceStore()
      store.toggleHistory()
      expect(store.historyOpen).toBe(true)

      spoken(store)
      store.toggleHistory()
      expect(store.historyOpen).toBe(false)
      // 关抽屉本身不算新内容：徽标仍为清除状态，直到下一条东西到达。
      expect(store.unread).toBe(false)
    })
  })

  // 抽屉里的「Interrupted」行（demo `_markHistInterrupted`）：被打断的回复要留在
  // 历史里，并且后面的计时必须挂在它自己身上。
  it('marks the interrupted reply and still hands it the timings', () => {
    const store = useVoiceStore()
    store.applyEvent({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: 'question' })
    store.applyEvent({ type: 'response.audio_transcript.done', response_id: 'r1', transcript: 'answer' })
    store.markInterrupted('r1', 'answer')
    store.attachLatency({
      version: 2,
      turn_id: 't1',
      turn_revision: 0,
      response_key: 'r1',
      status: 'cancelled',
      stt_s: 0.1,
      llm_s: null,
      tts_ttfa_s: 0.1,
      e2e_s: 0.4,
      vad_decision_s: null,
      smart_status: 'disabled',
      hold_s: null
    })

    expect(store.entries).toHaveLength(2)
    expect(store.entries[1]).toMatchObject({ role: 'assistant', text: 'answer', interrupted: true, latency: { e2e_s: 0.4 } })
    // 打断也算新内容：抽屉关着时徽标仍然点亮。
    expect(store.unread).toBe(true)
  })
})
