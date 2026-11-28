// @vitest-environment jsdom
// SessionCards 卡片流（原型 .sess 卡）：状态徽标 + 逐行转写 + 可播放片段条。
import { createApp, defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'

import i18n from '@/i18n'
import SessionCards from './SessionCards.vue'
import type { SessionCardLine, SessionCardVM } from './SessionCards.vue'
import { waveBars } from './waveBars'

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

function mountCards(cards: SessionCardVM[]): HTMLDivElement {
  const root = document.createElement('div')
  document.body.appendChild(root)
  roots.push(root)
  const app = createApp(
    defineComponent({
      setup() {
        return () => h(SessionCards, { cards })
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

const card = (overrides: Partial<SessionCardVM> = {}): SessionCardVM => ({
  key: 'c1',
  kind: 'saved',
  state: 'done',
  when: '12:00',
  inst: 'inst-1',
  node: 'node-a',
  lines: [],
  id: 'psid-1',
  turns: 2,
  durMs: 15000,
  ttfaMs: 660,
  ...overrides
})

const line = (overrides: Partial<SessionCardLine> = {}): SessionCardLine => ({
  role: 'user',
  ordinal: 0,
  asr: '你好',
  text: '',
  stt: 'ok',
  tts: 'none',
  durMs: 3800,
  audioUrl: null,
  ...overrides
})

describe('SessionCards 卡片流', () => {
  it('live 卡：进行中徽标 + live 状态点', () => {
    const root = mountCards([card({ kind: 'live', state: 'live' })])
    expect(root.querySelector('.scard__dot[data-state="live"]')).not.toBeNull()
    expect(root.querySelector('.scard')?.querySelector('.badge')?.textContent).toContain('进行中')
  })

  it('unsaved 卡：渲染「未保存」徽标', () => {
    const root = mountCards([card({ state: 'unsaved' })])
    expect(root.textContent).toContain('未保存')
  })

  it('partial 卡：渲染「部分片段缺失」徽标', () => {
    const root = mountCards([card({ state: 'partial' })])
    expect(root.textContent).toContain('部分片段缺失')
  })

  it('带音频的行渲染片段 pill（12 根波形条 + 时长）与 stt 标记', () => {
    const root = mountCards([card({ lines: [line({ audioUrl: 'blob:x' })] })])
    const pill = root.querySelector('.clip')
    expect(pill).not.toBeNull()
    expect(pill?.querySelectorAll('.clip__bars i')).toHaveLength(12)
    expect(pill?.querySelector('.clip__dur')?.textContent).toContain('0:04')
    expect(root.textContent).toContain('已转写')
  })

  it('无音频的行不渲染 pill，显示「无音频」徽标', () => {
    const root = mountCards([card({ lines: [line({ audioUrl: null })] })])
    expect(root.querySelector('.clip')).toBeNull()
    expect(root.textContent).toContain('无音频')
  })

  it('助理行渲染回复文本与 tts 标记', () => {
    const root = mountCards([
      card({ lines: [line({ role: 'assistant', asr: '', text: '你好，有什么可以帮你？', tts: 'ok', stt: 'none' })] })
    ])
    expect(root.textContent).toContain('你好，有什么可以帮你？')
    expect(root.textContent).toContain('已合成')
    expect(root.textContent).toContain('回复')
  })
})

describe('waveBars（原型同款确定性伪随机波形）', () => {
  it('同 seed 两次结果完全一致', () => {
    expect(waveBars('clip-1')).toEqual(waveBars('clip-1'))
    expect(waveBars('clip-1')).not.toEqual(waveBars('clip-2'))
  })

  it('默认 12 根、值域 3..11', () => {
    for (const seed of ['a', 'psid-9', 'xxxx-long-seed-value']) {
      const bars = waveBars(seed)
      expect(bars).toHaveLength(12)
      for (const h of bars) {
        expect(h).toBeGreaterThanOrEqual(3)
        expect(h).toBeLessThanOrEqual(11)
      }
    }
  })
})
