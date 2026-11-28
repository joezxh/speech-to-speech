import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import * as sessionRecordsApi from '@/api/sessionRecords'
import { useSessionRecordsStore, toSavePayload } from '@/stores/sessionRecords'
import type { SessionRecordRow } from '@/api/sessionRecords'
import type { TranscriptEntry } from '@/features/voice/types'

vi.mock('@/api/sessionRecords', () => ({
  listSessionRecords: vi.fn(),
  sessionRecordStats: vi.fn(),
  getSessionRecord: vi.fn(),
  saveSessionRecord: vi.fn(),
  updateSessionRecord: vi.fn(),
  deleteSessionRecord: vi.fn(),
  deleteSessionRecords: vi.fn(),
  updateSessionMessage: vi.fn(),
  deleteSessionMessage: vi.fn(),
  clearSessionMessages: vi.fn(),
  listRouteLogs: vi.fn(),
  listSessionRecordInstances: vi.fn()
}))

const entry = (overrides: Partial<TranscriptEntry>): TranscriptEntry => ({
  key: 'a:1',
  role: 'assistant',
  text: '',
  partial: false,
  ...overrides
})

const row = (overrides: Partial<SessionRecordRow>): SessionRecordRow => ({
  id: 1,
  userId: 'alice',
  title: '未命名会话',
  note: '',
  pipelineSessionId: 'sess-1',
  instanceId: '',
  node: 'pipe-a',
  state: 'done',
  turns: 2,
  durationMs: 15000,
  ttfaMs: 660,
  createdAt: '2026-11-28T10:00:00Z',
  updatedAt: '2026-11-28T10:00:00Z',
  messageCount: 3,
  excerpt: '你好 · 你好，有什么可以帮你？ · search(...)',
  ...overrides
})

const latency = (e2eS: number) => ({
  version: 1,
  turn_id: null,
  turn_revision: 1,
  response_key: 'r1',
  status: 'ok',
  stt_s: 0.4,
  llm_s: 0.6,
  tts_ttfa_s: 0.66,
  e2e_s: e2eS
})

describe('toSavePayload', () => {
  it('keeps stt/tts failure rows and derives status/durationMs', () => {
    const payload = toSavePayload([
      entry({ key: 'u:1', role: 'user', text: '', audio: { url: 'blob:x', durationMs: 3800, truncated: false } }),
      entry({ key: 'a:1', role: 'assistant', text: '好', latency: latency(1.8) }),
      entry({ key: 'a:2', role: 'assistant', text: '', interrupted: true, latency: latency(0.5) }),
      entry({ key: 't:1', role: 'tool', text: 'search()' }),
      entry({ key: 'u:2', role: 'user', text: '  ' })
    ])
    expect(payload.messages).toHaveLength(4)
    expect(payload.messages[0]).toMatchObject({ role: 'user', status: 'fail', durationMs: 3800 })
    expect(payload.messages[1]).toMatchObject({ role: 'assistant', status: 'ok', durationMs: 1800 })
    expect(payload.messages[2]).toMatchObject({ role: 'assistant', status: 'fail', durationMs: 500 })
    expect(payload.messages[3]).toMatchObject({ role: 'tool', status: 'ok', durationMs: 0 })
    expect(payload.turns).toBe(2)
  })

  it('drops empty lines, counts assistant turns and converts TTFA s→ms', () => {
    const payload = toSavePayload(
      [
        entry({ key: 'u:1', role: 'user', text: '你好' }),
        entry({ key: 'a:1', role: 'assistant', text: '你好', latency: { version: 1, turn_id: null, turn_revision: 1, response_key: 'r1', status: 'ok', stt_s: 0.4, llm_s: 0.6, tts_ttfa_s: 0.66, e2e_s: 1.8 } }),
        entry({ key: 'u:2', role: 'user', text: '  ' }),
        entry({ key: 't:1', role: 'tool', text: 'search()', interrupted: false })
      ],
      { pipelineSessionId: 's1', durationMs: 1500.6 }
    )
    expect(payload.messages).toHaveLength(3)
    expect(payload.turns).toBe(1)
    expect(payload.ttfaMs).toBe(660)
    expect(payload.durationMs).toBe(1501)
    expect(payload.pipelineSessionId).toBe('s1')
    expect(payload.state).toBe('done')
  })

  it('marks state failed and keeps interrupted flag', () => {
    const payload = toSavePayload([entry({ text: 'partial', interrupted: true })], { state: 'failed' })
    expect(payload.state).toBe('failed')
    expect(payload.messages[0].interrupted).toBe(true)
  })
})

describe('sessionRecords store', () => {
  const api = vi.mocked(sessionRecordsApi, true)

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.listSessionRecords.mockResolvedValue({ list: [row({}), row({ id: 2, title: '周一调解' })], total: 2, page: 1, pageSize: 20 })
    api.sessionRecordStats.mockResolvedValue({ total: 2, done: 2, failed: 0, turns: 4, avgDurationMs: 15000, avgTtfaMs: 660 })
    api.getSessionRecord.mockResolvedValue(row({ messages: [{ id: 11, ordinal: 0, role: 'user', type: 'audio', content: '你好', interrupted: false, status: 'ok', durationMs: 3800, createdAt: 't' }] }))
    api.saveSessionRecord.mockResolvedValue(row({ id: 9 }))
    api.listSessionRecordInstances.mockResolvedValue([{ instanceId: 'pipe-a', node: 'n1' }])
  })

  it('loads list + stats and applies filters', async () => {
    const store = useSessionRecordsStore()
    store.filters.state = 'failed'
    await store.load()
    expect(store.rows).toHaveLength(2)
    expect(api.listSessionRecords).toHaveBeenCalledWith(expect.objectContaining({ state: 'failed', page: 1, pageSize: 20 }))
    await store.loadStats()
    expect(store.stats?.total).toBe(2)
  })

  it('sends inst/range filters and loads instances list', async () => {
    const store = useSessionRecordsStore()
    store.filters.inst = 'pipe-a'
    store.filters.range = '7d'
    await store.load()
    expect(api.listSessionRecords).toHaveBeenCalledWith(expect.objectContaining({ inst: 'pipe-a', range: '7d' }))
    await store.loadInstances()
    expect(store.instances).toEqual([{ instanceId: 'pipe-a', node: 'n1' }])
  })

  it('removeMessage updates detail and row messageCount', async () => {
    const store = useSessionRecordsStore()
    await store.load()
    await store.openDetail(1)
    await store.removeMessage(1, 11)
    expect(api.deleteSessionMessage).toHaveBeenCalledWith(1, 11)
    expect(store.detail?.messages).toHaveLength(0)
    expect(store.rows[0].messageCount).toBe(2)
  })

  it('saveFromCall refreshes first page and keeps detail empty until opened', async () => {
    const store = useSessionRecordsStore()
    const saved = await store.saveFromCall({ title: '', messages: [{ role: 'user', type: 'text', content: 'hi' }] })
    expect(saved.id).toBe(9)
    expect(api.saveSessionRecord).toHaveBeenCalledTimes(1)
    expect(store.rows).toHaveLength(2)
  })

  it('openDetail loads messages; patchRecord updates list row in place', async () => {
    const store = useSessionRecordsStore()
    await store.load()
    await store.openDetail(1)
    expect(store.detail?.messages).toHaveLength(1)
    api.updateSessionRecord.mockResolvedValue(row({ title: '新标题' }))
    await store.patchRecord(1, { title: '新标题' })
    expect(store.rows[0].title).toBe('新标题')
  })

  it('removeMany drops rows, shrinks total and reloads stats', async () => {
    const store = useSessionRecordsStore()
    await store.load()
    await store.loadStats()
    api.deleteSessionRecords.mockResolvedValue({ deleted: 1 })
    await store.removeMany([1])
    expect(store.rows).toHaveLength(1)
    expect(store.total).toBe(1)
    expect(api.sessionRecordStats).toHaveBeenCalledTimes(2)
  })

  it('load failure keeps error and empties rows', async () => {
    const store = useSessionRecordsStore()
    api.listSessionRecords.mockRejectedValueOnce(new Error('boom'))
    await store.load()
    expect(store.error).toBe('boom')
    expect(store.rows).toEqual([])
  })
})
