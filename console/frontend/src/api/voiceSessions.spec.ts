import { describe, expect, it } from 'vitest'

import { turnAudioRequestPath } from './voiceSessions'

describe('turnAudioRequestPath', () => {
  it('drops the prefix the axios client already carries', () => {
    // `turn_payload.audioUrl` 是绝对路径，而 `client` 的 baseURL 同为 `/api/v1`：
    // 不摘前缀就会请求 `/api/v1/api/v1/...`，每个播放按钮都 404。
    expect(turnAudioRequestPath('/api/v1/voice-sessions/A/turns/B/audio')).toBe(
      '/voice-sessions/A/turns/B/audio'
    )
  })

  it('leaves an already relative path untouched', () => {
    expect(turnAudioRequestPath('/voice-sessions/A/turns/B/audio')).toBe('/voice-sessions/A/turns/B/audio')
    expect(turnAudioRequestPath('')).toBe('')
  })

  it('only cuts a whole segment, never a longer name that merely starts with it', () => {
    expect(turnAudioRequestPath('/api/v1preview')).toBe('/api/v1preview')
    expect(turnAudioRequestPath('/api/v1')).toBe('')
  })
})
