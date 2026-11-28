// @vitest-environment jsdom
// StageTranscript（对话图标下方的持久双侧转写，对齐原型 .transcript）。
// 挂载手法沿用 HistoryView.spec.ts（createApp 手挂 + 手动 unmount）。
import { createApp, defineComponent, h, nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'

import i18n from '@/i18n'
import StageTranscript from './StageTranscript.vue'
import type { TranscriptEntry } from '@/features/voice/types'

const entry = (overrides: Partial<TranscriptEntry>): TranscriptEntry => ({
  key: 'a:1',
  role: 'assistant',
  text: '',
  partial: false,
  ...overrides
})

let roots: HTMLDivElement[] = []

function mountComp(entries: TranscriptEntry[]) {
  const root = document.createElement('div')
  document.body.appendChild(root)
  roots.push(root)
  const app = createApp(defineComponent({ render: () => h(StageTranscript, { entries }) }))
  app.use(i18n)
  app.mount(root)
  return root
}

afterEach(() => {
  roots.splice(0).forEach((root) => root.remove())
})

describe('StageTranscript 对齐原型 .bubble 两侧分布', () => {
  it('user 行右对齐、assistant/tool 行左对齐', async () => {
    const root = mountComp([
      entry({ key: 'u:1', role: 'user', text: '你好' }),
      entry({ key: 'a:1', role: 'assistant', text: '你好，需要什么帮助？' }),
      entry({ key: 't:1', role: 'tool', text: 'search(天气)' })
    ])
    await nextTick()
    const rows = Array.from(root.querySelectorAll('[data-role]'))
    expect(rows).toHaveLength(3)
    expect(rows[0].className).toContain('st__bubble--user')
    expect(rows[1].className).toContain('st__bubble--assistant')
    expect(rows[2].className).toContain('st__bubble--tool')
    expect(rows[0].textContent).toContain('你好')
  })

  it('空通话只渲染居中 meta 提示', async () => {
    const root = mountComp([])
    await nextTick()
    expect(root.querySelector('.st__meta')).toBeTruthy()
    expect(root.querySelector('[data-role]')).toBeNull()
  })

  it('partial 行带输入省略标记', async () => {
    const root = mountComp([entry({ key: 'u:1', role: 'user', text: '正在说', partial: true })])
    await nextTick()
    expect(root.querySelector('[data-partial="true"]')).toBeTruthy()
  })
})
