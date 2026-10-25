import { describe, expect, it } from 'vitest'

import { buildDirectWsUrl, sameOriginRealtimeUrl } from '@/features/voice/transport/s2s-client'

// 这两支函数决定声音到底拨向哪里：直连模式（没有 LB）不再请求 `/api/session`，
// 而是把部署钉死的地址、或同源 `/v1/realtime` 交给 WebSocket。规则与
// demo/main.js:962-980 同源，这里逐条钉住，免得回归时静默改地址。

describe('buildDirectWsUrl', () => {
  it('is empty when the deployment pins nothing (caller falls back to same origin)', () => {
    expect(buildDirectWsUrl('')).toBe('')
    expect(buildDirectWsUrl('   ')).toBe('')
  })

  it('turns a loopback http URL into ws + /v1/realtime', () => {
    expect(buildDirectWsUrl('http://127.0.0.1:8765')).toBe('ws://127.0.0.1:8765/v1/realtime')
    expect(buildDirectWsUrl('http://localhost:8765/')).toBe('ws://localhost:8765/v1/realtime')
  })

  it('accepts a bare host:port — localhost stays ws, anything else gets wss', () => {
    expect(buildDirectWsUrl('localhost:8765')).toBe('ws://localhost:8765/v1/realtime')
    expect(buildDirectWsUrl('s2s.example.com')).toBe('wss://s2s.example.com/v1/realtime')
  })

  it('maps https to wss without touching a public https address', () => {
    expect(buildDirectWsUrl('https://s2s.example.com')).toBe('wss://s2s.example.com/v1/realtime')
  })

  it('keeps an explicit ws/wss path and query instead of appending one', () => {
    expect(buildDirectWsUrl('ws://127.0.0.1:8765/v1/realtime')).toBe('ws://127.0.0.1:8765/v1/realtime')
    expect(buildDirectWsUrl('wss://s2s.example.com/custom?lang=zh')).toBe('wss://s2s.example.com/custom?lang=zh')
  })
})

describe('sameOriginRealtimeUrl', () => {
  it('dials the console proxy that forwards to PIPELINE_BASE_URL', () => {
    expect(sameOriginRealtimeUrl('http://localhost:3000/console/params?x=1')).toBe('ws://localhost:3000/v1/realtime')
    expect(sameOriginRealtimeUrl('https://s2s.example.com/')).toBe('wss://s2s.example.com/v1/realtime')
  })

  it('is empty when there is no page location to derive from', () => {
    expect(sameOriginRealtimeUrl('')).toBe('')
  })
})
