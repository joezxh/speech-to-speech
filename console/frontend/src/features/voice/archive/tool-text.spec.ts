import { describe, expect, it } from 'vitest'

import { toolCallText, toolResultText } from './tool-text'

describe('toolCallText', () => {
  it('keeps the arguments the model actually sent', () => {
    expect(toolCallText({ name: 'web_search', arguments: '{"query":"paris"}', callId: 'c1' })).toBe(
      'web_search({"query":"paris"})'
    )
  })

  it('drops an empty parameter object', () => {
    expect(toolCallText({ name: 'camera_snapshot', arguments: '{}', callId: 'c2' })).toBe('camera_snapshot')
    expect(toolCallText({ name: 'camera_snapshot', arguments: '   ', callId: 'c2' })).toBe('camera_snapshot')
  })

  it('survives a missing name instead of archiving an empty line', () => {
    expect(toolCallText({ name: '', arguments: '', callId: 'c3' })).toBe('tool')
  })
})

describe('toolResultText', () => {
  it('joins the call and its output into one line', () => {
    expect(
      toolResultText({ name: 'web_search', arguments: '{"query":"paris"}', callId: 'c1', output: '18°C and sunny' })
    ).toBe('web_search({"query":"paris"}) → 18°C and sunny')
  })

  it('marks the output the user will never see', () => {
    const snapshot = { name: 'camera_snapshot', arguments: '{}', callId: 'c2', output: '', image: 'data:image/png;base64,AA' }
    expect(toolResultText(snapshot)).toBe('camera_snapshot → [image]')
    // A base64 frame must not end up in the transcript column, however small it is.
    expect(toolResultText(snapshot)).not.toContain('base64')
    expect(toolResultText({ name: 'web_search', arguments: '{}', callId: 'c3', output: '' })).toBe('web_search → [no output]')
  })

  it('says so when the tool failed', () => {
    expect(toolResultText({ name: 'web_search', arguments: '{}', callId: 'c4', output: 'quota exceeded', failed: true })).toBe(
      'web_search → quota exceeded (failed)'
    )
  })
})
