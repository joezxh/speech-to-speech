import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { smartSettingsApi } from '@/api/smartSettings'
import { useSmartSettingsStore } from '@/stores/smartSettings'

vi.mock('@/api/smartSettings', () => ({
  smartSettingsApi: { fetch: vi.fn(), analyze: vi.fn() }
}))

// store 失败路径走 i18n.global.t；测试环境用桩替掉整棵 i18n 树。
vi.mock('@/i18n', () => ({ default: { global: { t: (key: string) => key } } }))

describe('smartSettings store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('fetch stores machine params and logs', async () => {
    vi.mocked(smartSettingsApi.fetch).mockResolvedValue({
      machine: { machineId: 'node-a01', platform: 'gpu', driver: '', gpu: 'L40S', gpuTotalGb: 48, state: 'ok', version: '' },
      params: [{ key: 'vad.min_silence_ms', expected: '450', actual: '400', drift: false, source: 'console', effect: 'hot', exposure: 'core', risk: '', anchor: '' }],
      logs: [{ ts: '2026-11-28T10:00:00Z', level: 'info', text: 'ok' }]
    })
    const store = useSmartSettingsStore()
    const result = await store.fetch('node-a01')
    expect(result?.params).toHaveLength(1)
    expect(store.data.fetched?.logs).toHaveLength(1)
    expect(store.data.error).toBeNull()
  })

  it('analyze collects actual params and log lines from the fetched snapshot', async () => {
    vi.mocked(smartSettingsApi.fetch).mockResolvedValue({
      machine: { machineId: 'node-a01', platform: 'gpu', driver: '', gpu: '', gpuTotalGb: null, state: 'ok', version: '' },
      params: [
        { key: 'vad.min_silence_ms', expected: '450', actual: '400', drift: false, source: '', effect: 'hot', exposure: '', risk: '', anchor: '' },
        { key: 'vad.max_speech_ms', expected: '20000', actual: null, drift: false, source: '', effect: 'start', exposure: '', risk: '', anchor: '' }
      ],
      logs: [{ ts: 'T1', level: 'warn', text: 'stall' }]
    })
    vi.mocked(smartSettingsApi.analyze).mockResolvedValue({
      summary: 's', source: 'llm', model: 'm',
      recommendations: [{ key: 'vad.min_silence_ms', from: '400', to: '700', reason: 'r' }],
      durationMs: 10, auditId: '1'
    })
    const store = useSmartSettingsStore()
    await store.fetch('node-a01')
    await store.analyze('node-a01', '总是被截断')
    expect(smartSettingsApi.analyze).toHaveBeenCalledWith({
      machineId: 'node-a01',
      fault: '总是被截断',
      // agent 未上报的行回退 expected 值，保证 LLM 能看到完整参数面。
      params: { 'vad.min_silence_ms': '400', 'vad.max_speech_ms': '20000' },
      logs: ['[T1] stall']
    })
    expect(store.data.analysis?.recommendations[0].to).toBe('700')
  })

  it('rejects an empty fault without hitting the API', async () => {
    const store = useSmartSettingsStore()
    expect(await store.analyze('node-a01', '   ')).toBeNull()
    expect(store.data.error?.code).toBe('invalid_parameter')
    expect(smartSettingsApi.analyze).not.toHaveBeenCalled()
  })

  it('fetch failures clear the snapshot and surface the error', async () => {
    vi.mocked(smartSettingsApi.fetch).mockRejectedValue(new Error('boom'))
    const store = useSmartSettingsStore()
    expect(await store.fetch('ghost')).toBeNull()
    expect(store.data.fetched).toBeNull()
    expect(store.data.error).not.toBeNull()
  })
})
