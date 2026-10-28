// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createLocaleStore } from './locale.test-harness'

// 通过 harness 注入受控 navigator/localStorage，见 Step 5。
describe('locale store', () => {
  beforeEach(() => localStorage.clear())

  it('prefers a stored locale', () => {
    localStorage.setItem('s2s.console.locale', 'en-US')
    expect(createLocaleStore().locale).toBe('en-US')
  })

  it('falls back to navigator.language (zh prefix)', () => {
    vi.stubGlobal('navigator', { language: 'zh-TW' })
    expect(createLocaleStore().locale).toBe('zh-CN')
    vi.unstubAllGlobals()
  })

  it('defaults non-zh navigator to en-US', () => {
    vi.stubGlobal('navigator', { language: 'fr-FR' })
    expect(createLocaleStore().locale).toBe('en-US')
    vi.unstubAllGlobals()
  })

  it('persists on setLocale', () => {
    const store = createLocaleStore()
    store.setLocale('zh-CN')
    expect(localStorage.getItem('s2s.console.locale')).toBe('zh-CN')
  })
})
