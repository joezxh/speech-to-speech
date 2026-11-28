// @vitest-environment jsdom
// SessionRecordDetail 片段回放：clips 按 messageOrdinal 对齐消息行；404 → 片段条禁用不抛错。
import { createApp, defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import * as sessionRecordsApi from '@/api/sessionRecords'
import i18n from '@/i18n'
import SessionRecordDetail from './SessionRecordDetail.vue'
import type { SessionRecordRow } from '@/api/sessionRecords'

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
  listSessionRecordInstances: vi.fn(),
  uploadSessionClip: vi.fn(),
  fetchSessionClipUrl: vi.fn()
}))

let roots: HTMLDivElement[] = []

function mountDetail(recordId = 1): HTMLDivElement {
  const root = document.createElement('div')
  document.body.appendChild(root)
  roots.push(root)
  const app = createApp(
    defineComponent({
      setup() {
        return () => h(SessionRecordDetail, { recordId, onClose: () => {}, onChanged: () => {} })
      }
    })
  )
  app.use(i18n)
  app.use(createPinia())
  app.mount(root)
  return root
}

afterEach(() => {
  roots.splice(0).forEach((root) => root.remove())
})

const detailRow = (overrides: Partial<SessionRecordRow> = {}): SessionRecordRow => ({
  id: 1,
  userId: 'alice',
  title: '调解通话',
  note: '',
  pipelineSessionId: 'psid-1',
  instanceId: '',
  node: 'node-a',
  state: 'done',
  turns: 2,
  durationMs: 15000,
  ttfaMs: 660,
  createdAt: '2026-11-28T10:00:00Z',
  updatedAt: '2026-11-28T10:00:00Z',
  messageCount: 2,
  excerpt: '',
  messages: [
    { id: 11, ordinal: 0, role: 'user', type: 'audio', content: '你好', interrupted: false, status: 'ok', durationMs: 3800, createdAt: 't' },
    { id: 12, ordinal: 1, role: 'assistant', type: 'text', content: '你好，有什么可以帮你？', interrupted: false, status: 'ok', durationMs: 1800, createdAt: 't' }
  ],
  clips: [
    { id: 7, role: 'user', itemRef: '1', messageOrdinal: 0, durationMs: 3800, sizeBytes: 152000 },
    { id: 8, role: 'assistant', itemRef: '2', messageOrdinal: 1, durationMs: 1800, sizeBytes: 90000 }
  ],
  ...overrides
})

const api = vi.mocked(sessionRecordsApi, true)

describe('SessionRecordDetail 片段回放', () => {
  it('clips 按 messageOrdinal 对齐消息行：每条消息行下渲染对应片段 pill', async () => {
    setActivePinia(createPinia())
    api.getSessionRecord.mockResolvedValue(detailRow())
    const root = mountDetail(1)
    await Promise.resolve()
    await Promise.resolve()
    const pills = Array.from(root.querySelectorAll('.srd__msg .clip'))
    expect(pills).toHaveLength(2)
    expect(api.fetchSessionClipUrl).not.toHaveBeenCalled()
  })

  it('回放成功：按 (recordId, clipId) 拉字节并进入播放态', async () => {
    setActivePinia(createPinia())
    api.getSessionRecord.mockResolvedValue(detailRow())
    api.fetchSessionClipUrl.mockResolvedValue('blob:playback')
    const root = mountDetail(1)
    await Promise.resolve()
    await Promise.resolve()
    const pill = root.querySelector('.srd__msg .clip') as HTMLButtonElement
    pill.click()
    await Promise.resolve()
    await Promise.resolve()
    expect(api.fetchSessionClipUrl).toHaveBeenCalledWith(1, 7)
    expect(pill.dataset.playing).toBe('true')
  })

  it('片段缺失（404）：片段条转为禁用态，不抛错', async () => {
    setActivePinia(createPinia())
    api.getSessionRecord.mockResolvedValue(detailRow())
    api.fetchSessionClipUrl.mockRejectedValue(new Error('404'))
    const root = mountDetail(1)
    await Promise.resolve()
    await Promise.resolve()
    const pill = root.querySelector('.srd__msg .clip') as HTMLButtonElement
    expect(() => pill.click()).not.toThrow()
    await Promise.resolve()
    await Promise.resolve()
    expect(pill.disabled).toBe(true)
    expect(pill.title).toContain('不可回放')
    // 另一条消息的片段不受影响
    const other = root.querySelectorAll('.srd__msg .clip')[1] as HTMLButtonElement
    expect(other.disabled).toBe(false)
  })
})
