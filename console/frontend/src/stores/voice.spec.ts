import { beforeEach, describe, expect, it } from 'vitest'
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
})
