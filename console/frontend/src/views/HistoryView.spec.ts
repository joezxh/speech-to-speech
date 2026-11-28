// @vitest-environment jsdom
// 历史页对齐原型（2026-11-28）：KPI 四卡、inst/range 筛选、页内消息面板、摘录/时长空值 —。
// 挂载手法沿用 proto.spec.ts（createApp 手挂 + 手动 unmount）；a-modal/a-button 用渲染函数桩。
import { createApp, defineComponent, h, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'

import * as sessionRecordsApi from '@/api/sessionRecords'
import type { SessionRecordRow } from '@/api/sessionRecords'
import i18n from '@/i18n'
import HistoryView from './HistoryView.vue'

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

const row = (overrides: Partial<SessionRecordRow>): SessionRecordRow => ({
  id: 1,
  userId: 'alice',
  title: '未命名会话',
  note: '',
  pipelineSessionId: 'sess-1',
  instanceId: 'pipe-a',
  node: 'n1',
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

const message = (overrides: Record<string, unknown>) => ({
  id: 11,
  ordinal: 0,
  role: 'user',
  type: 'audio',
  content: '你好',
  interrupted: false,
  status: 'ok',
  durationMs: 3800,
  createdAt: '2026-11-28T10:00:01Z',
  ...overrides
})

let roots: HTMLDivElement[] = []

const AModalStub = defineComponent({
  props: { open: { type: Boolean, default: false }, title: { type: String, default: '' } },
  setup(props, { slots }) {
    return () => (props.open ? h('div', { class: 'stub-modal' }, slots.default?.()) : null)
  }
})
const AButtonStub = defineComponent({
  inheritAttrs: false,
  setup(_, { attrs, slots }) {
    return () => h('button', { ...attrs, type: 'button' }, slots.default?.())
  }
})

function mount(): HTMLElement {
  const root = document.createElement('div')
  document.body.appendChild(root)
  roots.push(root)
  const app = createApp(defineComponent({ render: () => h(HistoryView) }))
  app.use(createPinia())
  app.use(i18n)
  app.component('a-modal', AModalStub)
  app.component('a-button', AButtonStub)
  app.mount(root)
  return root
}

afterEach(() => {
  for (const root of roots) {
    try {
      ;(root as never as { __vue_app__: { unmount: () => void } }).__vue_app__.unmount()
    } catch {
      /* already gone */
    }
    root.remove()
  }
  roots = []
})

const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

describe('HistoryView（原型对齐）', () => {
  const api = vi.mocked(sessionRecordsApi, true)

  beforeEach(() => {
    vi.clearAllMocks()
    api.listSessionRecords.mockResolvedValue({
      list: [
        row({}),
        row({ id: 2, durationMs: 0, messageCount: 0, excerpt: '', state: 'failed', ttfaMs: null })
      ],
      total: 2,
      page: 1,
      pageSize: 20
    })
    api.sessionRecordStats.mockResolvedValue({
      total: 2,
      done: 1,
      failed: 1,
      turns: 3,
      avgDurationMs: 15000,
      avgTtfaMs: 660
    })
    api.getSessionRecord.mockResolvedValue(
      row({ messages: [message({}), message({ id: 12, ordinal: 1, role: 'assistant', type: 'text', content: '你好，有什么可以帮你？', status: 'ok', durationMs: 1800, createdAt: '2026-11-28T10:00:02Z' })] })
    )
    api.listSessionRecordInstances.mockResolvedValue([{ instanceId: 'pipe-a', node: 'n1' }])
  })

  it('renders four KPI cards incl. avg TTFT in ms', async () => {
    const root = mount()
    await flush()
    await nextTick()
    const text = root.querySelector('.hv__kpis')?.textContent ?? ''
    expect(text).toContain('660ms')
    expect(text).toContain('平均 TTFT')
    expect(root.querySelectorAll('.hv__kpi')).toHaveLength(4)
  })

  it('submits inst/range filters to the list API', async () => {
    const root = mount()
    await flush()
    await nextTick()

    const inst = root.querySelector<HTMLSelectElement>('#hist-inst')
    const range = root.querySelector<HTMLSelectElement>('#hist-range')
    expect(inst).not.toBeNull()
    inst!.value = 'pipe-a'
    inst!.dispatchEvent(new Event('change'))
    range!.value = '7d'
    range!.dispatchEvent(new Event('change'))
    root.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await flush()
    await nextTick()

    expect(api.listSessionRecords).toHaveBeenLastCalledWith(expect.objectContaining({ inst: 'pipe-a', range: '7d' }))
  })

  it('opens the inline message panel on row click, highlights the row, closes on second click', async () => {
    const root = mount()
    await flush()
    await nextTick()

    const firstRow = root.querySelector('tbody tr.clickable') as HTMLTableRowElement
    firstRow.click()
    await flush()
    await nextTick()

    expect(root.querySelector('.hv__panel')).not.toBeNull()
    expect(firstRow.classList.contains('sel')).toBe(true)

    firstRow.click()
    await nextTick()
    expect(root.querySelector('.hv__panel')).toBeNull()
    expect(firstRow.classList.contains('sel')).toBe(false)
  })

  it('deletes a message from the panel after confirming', async () => {
    const root = mount()
    await flush()
    await nextTick()

    ;(root.querySelector('tbody tr.clickable') as HTMLTableRowElement).click()
    await flush()
    await nextTick()

    const del = Array.from(root.querySelectorAll('.hv__panel tbody button')).find((b) => b.classList.contains('danger'))
    ;(del as HTMLButtonElement).click()
    await flush()
    await nextTick()

    const confirm = Array.from(root.querySelectorAll<HTMLButtonElement>('.stub-modal button')).pop()
    expect(confirm).not.toBeNull()
    ;(confirm as HTMLButtonElement).click()
    await flush()
    await nextTick()

    expect(api.deleteSessionMessage).toHaveBeenCalledWith(expect.anything(), expect.anything())
  })

  it('renders dash for empty excerpt and zero duration', async () => {
    const root = mount()
    await flush()
    await nextTick()
    const rowsText = Array.from(root.querySelectorAll('tbody tr')).map((tr) => tr.textContent ?? '')
    expect(rowsText[0]).toContain('你好')
    // 第二行：excerpt 空、durationMs=0、ttfaMs=null —— 展示层一律显示 —。
    expect(rowsText[1]).toContain('—')
    expect(rowsText[1]).not.toContain('你好')
  })
})
