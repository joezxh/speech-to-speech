import { createPinia, setActivePinia } from 'pinia'

import { detectLocale, type Locale } from '@/i18n/locale'

/** 测试专用：直接跑 detectLocale + 一个把 setLocale 落到 localStorage 的最小实现。 */
export function createLocaleStore(): { locale: Locale; setLocale: (n: Locale) => void } {
  setActivePinia(createPinia())
  const state: { locale: Locale } = { locale: detectLocale() }
  return {
    get locale() {
      return state.locale
    },
    setLocale(n: Locale) {
      state.locale = n
      localStorage.setItem('s2s.console.locale', n)
    }
  }
}
