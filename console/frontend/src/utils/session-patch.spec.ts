import { describe, expect, it } from 'vitest'

import { buildSessionPatch } from './session-patch'

const EMPTY = {
  instructions: '',
  createResponse: null,
  interruptResponse: null,
  language: '',
  extensions: ''
}

describe('buildSessionPatch', () => {
  it('refuses an empty form instead of sending a no-op patch', () => {
    const built = buildSessionPatch(EMPTY)
    expect(built.session).toEqual({})
    expect(built.problems).toEqual(['至少填写一个字段'])
  })

  it('sends only what the operator filled in, trimmed', () => {
    const built = buildSessionPatch({ ...EMPTY, instructions: '  只说两句话  ' })
    expect(built.problems).toEqual([])
    expect(built.session).toEqual({ instructions: '只说两句话' })
  })

  it('treats false as a value, not as “unset”', () => {
    const built = buildSessionPatch({ ...EMPTY, interruptResponse: false })
    expect(built.session).toEqual({
      audio: { input: { turn_detection: { interrupt_response: false } } }
    })
  })

  it('nests the language under audio.input.transcription', () => {
    const built = buildSessionPatch({ ...EMPTY, language: ' zh ' })
    expect(built.session).toEqual({ audio: { input: { transcription: { language: 'zh' } } } })
  })

  it('keeps the valid half and reports broken extensions JSON', () => {
    const built = buildSessionPatch({ ...EMPTY, instructions: 'hi', extensions: '{oops' })
    expect(built.problems).toEqual(['extensions 不是合法 JSON'])
    expect(built.session).toEqual({ instructions: 'hi' })
  })
})
