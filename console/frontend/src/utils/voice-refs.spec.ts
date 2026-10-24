import { describe, expect, it } from 'vitest'

import { bindPatch, bindings, conflicts, selectable, voiceIdIn, voiceSlot } from './voice-refs'
import type { VoiceRow } from '@/types/voice-library'

function voice(overrides: Partial<VoiceRow> = {}): VoiceRow {
  return {
    id: '01JABCDEFG',
    name: '嘉嘉',
    source: 'clone',
    backend: 'qwen3',
    language: 'zh',
    status: 'ready',
    audioSeconds: 8,
    createdAt: '2026-10-25T00:00:00Z',
    createdBy: 'alice',
    refCount: 0,
    usedBy: { profiles: [], versions: 0 },
    ...overrides
  }
}

const CACHE = '/app/data/voices/'

describe('bindings', () => {
  it('is the same table as the backend, so clone on kokoro is simply absent', () => {
    expect(bindings('builtin', 'qwen3')).toEqual({ speaker: 'qwen3_tts_speaker' })
    expect(bindings('clone', 'kokoro')).toBeNull()
    expect(bindings('clone', 'openai_compatible')).toBeNull()
    expect(bindings('design', 'kokoro')).toBeNull()
  })
})

describe('bindPatch', () => {
  it('uses spk + rvq once ready, and refAudio before that — never both', () => {
    const fields = bindings('clone', 'qwen3')!
    const ready = bindPatch(voice(), fields, CACHE)
    expect(ready).toEqual({
      qwen3_tts_speaker: null,
      qwen3_tts_ref_spk: '/app/data/voices/01JABCDEFG/spk.npy',
      qwen3_tts_ref_rvq: '/app/data/voices/01JABCDEFG/rvq.npy',
      qwen3_tts_ref_text: ''
    })

    const pending = bindPatch(voice({ status: 'failed' }), fields, CACHE)
    expect(pending).toEqual({
      qwen3_tts_speaker: null,
      qwen3_tts_ref_audio: '/app/data/voices/01JABCDEFG/ref.wav',
      qwen3_tts_ref_text: ''
    })
    expect(pending).not.toHaveProperty('qwen3_tts_ref_spk')
  })

  it('binds a builtin by name and a design by instruction', () => {
    expect(bindPatch(voice({ source: 'builtin', name: 'Aiden' }), bindings('builtin', 'qwen3')!, CACHE)).toEqual({
      qwen3_tts_speaker: 'Aiden'
    })
    expect(
      bindPatch(voice({ source: 'design', instruct: '低沉的男声' }), bindings('design', 'qwen3')!, CACHE)
    ).toEqual({ qwen3_tts_instruct: '低沉的男声' })
  })
})

describe('conflicts', () => {
  it('reports both the mutual exclusion and the missing rvq dependency', () => {
    expect(
      conflicts({
        qwen3_tts_ref_audio: '/a.wav',
        qwen3_tts_ref_spk: '/a.npy',
        qwen3_tts_ref_rvq: '/a.npy'
      })
    ).toEqual([
      { field: 'qwen3_tts_ref_spk', with: 'qwen3_tts_ref_audio' },
      { field: 'qwen3_tts_ref_rvq', reason: 'requires_spk_and_text' }
    ])
  })
})

describe('voiceSlot', () => {
  it('maps the voice fields to three slots, so one backend gets three pickers', () => {
    const slots = [
      voiceSlot('qwen3_tts_speaker'),
      voiceSlot('qwen3_tts_ref_spk'),
      voiceSlot('qwen3_tts_ref_audio'),
      voiceSlot('qwen3_tts_ref_text'),
      voiceSlot('qwen3_tts_instruct'),
      voiceSlot('qwen3_tts_ref_cache_dir'),
      voiceSlot('vad.thresh')
    ]
    expect(slots).toEqual(['builtin', 'clone', 'clone', 'clone', 'design', null, null])
    expect(new Set(slots.filter((slot) => slot !== null)).size).toBe(3)
  })
})

describe('selectable', () => {
  it('only offers ready voices of the same backend', () => {
    const rows = [
      voice(),
      voice({ id: 'B', status: 'precomputing' }),
      voice({ id: 'C', backend: 'kokoro' })
    ]
    expect(selectable(rows, 'qwen3').map((row) => row.id)).toEqual(['01JABCDEFG'])
  })
})

describe('voiceIdIn', () => {
  it('reads the id back out of a bound path, and refuses anything else', () => {
    expect(voiceIdIn('/app/data/voices/01JABCDEFG/spk.npy')).toBe('01JABCDEFG')
    expect(voiceIdIn('D:\\data\\voices\\X1\\ref.wav')).toBe('X1')
    expect(voiceIdIn('Aiden')).toBeNull()
    expect(voiceIdIn(null)).toBeNull()
  })
})
