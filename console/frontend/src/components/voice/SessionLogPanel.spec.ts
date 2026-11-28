// @vitest-environment jsdom
// SessionLogPanel 右栏常驻卡（对齐原型 .v-panel）：无 open/close，双 tab 常驻。
import { createApp, defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'

import * as sessionRecordsApi from '@/api/sessionRecords'
import i18n from '@/i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import SessionLogPanel from './SessionLogPanel.vue'

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

function mountPanelWithHandler(onUpdateTab: (value: 'log' | 'route') => void, tab: 'log' | 'route' = 'log') {
  const root = document.createElement('div')
  document.body.appendChild(root)
  roots.push(root)
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:x?', component: defineComponent({ render: () => null }) }] })
  const app = createApp(
    defineComponent({
      setup() {
        return () => h(SessionLogPanel, { tab, 'onUpdate:tab': onUpdateTab })
      }
    })
  )
  app.use(i18n)
  app.use(createPinia())
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
})
