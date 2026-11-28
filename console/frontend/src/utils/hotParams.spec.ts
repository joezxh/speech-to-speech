import { describe, expect, it } from 'vitest'

import { actualForParam, buildSessionPatch, isHotPath } from './hotParams'

describe('isHotPath', () => {
  it('accepts exactly the backend whitelist paths', () => {
    expect(isHotPath('instructions')).toBe(true)
    expect(isHotPath('extensions')).toBe(true)
    expect(isHotPath('audio.input.turn_detection.threshold')).toBe(true)
    expect(isHotPath('audio.input.turn_detection.silence_duration_ms')).toBe(true)
    expect(isHotPath('audio.input.transcription.language')).toBe(true)
  })

  it('rejects everything else (voice/model are NOT hot for the backend)', () => {
    expect(isHotPath('audio.output.voice')).toBe(false)
    expect(isHotPath('model')).toBe(false)
    expect(isHotPath('vad.min_silence_ms')).toBe(false)
  })

  it('null leaves allow the whole subtree, like the backend prune', () => {
    expect(isHotPath('audio.input.turn_detection')).toBe(true)
    expect(isHotPath('audio.input.turn_detection.create_response')).toBe(true)
    expect(isHotPath('audio.input.transcription')).toBe(false)
  })
})

describe('buildSessionPatch', () => {
  it('nests whitelisted values into the session.update shape', () => {
    const { patch, rejected } = buildSessionPatch({
      thresh: '0.55',
      min_silence_ms: '400',
      qwen3_asr_language: 'zh',
      instructions: 'be brief'
    })
    expect(patch).toEqual({
      instructions: 'be brief',
      audio: {
        input: {
          turn_detection: { threshold: '0.55', silence_duration_ms: '400' },
          transcription: { language: 'zh' }
        }
      }
    })
    expect(rejected).toEqual([])
  })

  it('rejects non-whitelisted params instead of sending them', () => {
    const { patch, rejected } = buildSessionPatch({ voice: 'Ryan', model: 'qwen3-8b', thresh: '0.6' })
    expect(patch).toEqual({ audio: { input: { turn_detection: { threshold: '0.6' } } } })
    expect(rejected).toEqual(['voice', 'model'])
  })

  it('ignores unknown names', () => {
    const { patch, rejected } = buildSessionPatch({ nope: '1' })
    expect(patch).toEqual({})
    expect(rejected).toEqual(['nope'])
  })
})

describe('actualForParam', () => {
  const rows = [
    { key: 'vad.min_silence_ms', actual: '450' },
    { key: 'min_silence_ms', actual: '999' },
    { key: 'llm.model_name', actual: null }
  ]

  it('prefers the exact catalog key, then the suffix match, then null', () => {
    expect(actualForParam(rows, 'vad.min_silence_ms')).toBe('450')
    expect(actualForParam(rows, 'vad.thresh')).toBeNull()
    expect(actualForParam([{ key: 'vad.thresh', actual: '0.5' }], 'vad.thresh')).toBe('0.5')
    expect(actualForParam(rows, 'llm.model_name')).toBeNull()
  })
})
