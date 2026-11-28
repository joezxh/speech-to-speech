// @vitest-environment jsdom
// SessionLogPanel 右栏常驻卡（对齐原型 .v-panel）：无 open/close，双 tab 常驻。
import { createApp, defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import i18n from '@/i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { useClusterStore } from '@/stores/cluster'
import { useVoiceStore } from '@/stores/voice'
import type { ClusterRow } from '@/types/api'
import SessionLogPanel from './SessionLogPanel.vue'
import type { LiveCard } from './SessionCards.vue'
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
  listRouteLogs: vi.fn().mockResolvedValue([]),
  listSessionRecordInstances: vi.fn().mockResolvedValue([]),
  uploadSessionClip: vi.fn(),
  fetchSessionClipUrl: vi.fn()
}))

let roots: HTMLDivElement[] = []

function mountPanel(tab: 'log' | 'route' = 'log') {
  return mountPanelWithHandler(() => {}, tab)
}

function mountPanelWithHandler(
  onUpdateTab: (value: 'log' | 'route') => void,
  tab: 'log' | 'route' = 'log',
  extra: { live?: LiveCard | null; saveState?: 'pending' | 'saved' | 'partial' | 'unsaved' } = {},
  pinia?: ReturnType<typeof createPinia>,
  onToolChange?: (key: 'web' | 'camera', value: boolean) => void
) {
  const root = document.createElement('div')
  document.body.appendChild(root)
  roots.push(root)
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:x?', component: defineComponent({ render: () => null }) }] })
  const app = createApp(
    defineComponent({
      setup() {
        return () =>
          h(SessionLogPanel, {
            tab,
            live: extra.live ?? null,
            saveState: extra.saveState ?? 'saved',
            'onUpdate:tab': onUpdateTab,
            'onTool-change': onToolChange
          })
      }
    })
  )
  app.use(i18n)
  app.use(pinia ?? createPinia())
  app.use(router)
  app.mount(root)
  return root
}

afterEach(() => {
  roots.splice(0).forEach((root) => root.remove())
})

describe('SessionLogPanel 右栏常驻卡', () => {
  it('不再有 open/close 抽屉语义：无关闭按钮，双 tab 常驻', () => {
    const root = mountPanel()
    expect(root.querySelector('.slp__close')).toBeNull()
    expect(root.querySelectorAll('[role="tab"]').length).toBe(2)
  })

  it('点 tab 发 update:tab', async () => {
    const seen: string[] = []
    const root = mountPanelWithHandler((value) => seen.push(value))
    const tabs = Array.from(root.querySelectorAll('[role="tab"]')) as HTMLButtonElement[]
    tabs[1].click()
    await Promise.resolve()
    expect(seen).toEqual(['route'])
  })

  it('传入 live 卡：卡片流置顶渲染 live 卡（进行中）', async () => {
    const entry: TranscriptEntry = { key: 'u:1', role: 'user', text: '你好', partial: false }
    const live: LiveCard = {
      entries: [entry],
      pipelineSessionId: 'psid-live',
      instanceId: 'inst-1',
      node: 'node-a',
      startedAtMs: Date.now()
    }
    const root = mountPanelWithHandler(() => {}, 'log', { live, saveState: 'pending' })
    await Promise.resolve()
    const liveCard = root.querySelector('.scard[data-kind="live"][data-state="live"]')
    expect(liveCard).not.toBeNull()
    expect(liveCard?.textContent).toContain('进行中')
    expect(liveCard?.textContent).toContain('你好')
  })
})

describe('SessionLogPanel 访问路由 tab（原型 v-row 键值行）', () => {
  const clusterRow: ClusterRow = {
    name: 'prod',
    registry: 'http://reg-a:2379',
    policy: 'least',
    note: '',
    machines_total: 3,
    machines_online: 2,
    instances_total: 4,
    healthy: true,
    updated_at: '2026-11-28T00:00:00Z',
    updated_by: 'ops'
  }

  it('键值行 ≥10，policy/registry 来自注入的集群数据', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const cluster = useClusterStore()
    cluster.rows = [clusterRow]
    cluster.current = 'prod'
    const root = mountPanelWithHandler(() => {}, 'route', {}, pinia)
    const rows = root.querySelectorAll('.v-row')
    expect(rows.length).toBeGreaterThanOrEqual(10)
    expect(root.textContent).toContain('least-in-use')
    expect(root.textContent).toContain('http://reg-a:2379')
    expect(root.textContent).toContain('300 s')
  })

  it('live 卡数据进键值行：端点 node:8765 与会话 ID', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const live: LiveCard = { entries: [], pipelineSessionId: 'psid-route', instanceId: 'inst-9', node: 'node-a', startedAtMs: Date.now() }
    const root = mountPanelWithHandler(() => {}, 'route', { live }, pinia)
    expect(root.textContent).toContain('node-a:8765')
    expect(root.textContent).toContain('psid-route')
    expect(root.textContent).toContain('inst-9')
  })

  it('当前音色来自 voice store；工具开关点击发 tool-change', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const voice = useVoiceStore()
    voice.loadSettings()
    const seen: Array<[string, boolean]> = []
    const root = mountPanelWithHandler(() => {}, 'route', {}, pinia, (key, value) => seen.push([key, value]))
    expect(root.textContent).toContain(voice.settings.voice)
    const switches = Array.from(root.querySelectorAll('[role="switch"]')) as HTMLButtonElement[]
    expect(switches.length).toBe(2)
    switches[0].click()
    await Promise.resolve()
    expect(seen).toEqual([['web', false]])
  })
})
