import { createI18n } from 'vue-i18n'

import enUS from './locales/en-US'
import zhCN from './locales/zh-CN'

const missingSeen = new Set<string>()

export default createI18n({
  legacy: false,
  locale: 'zh-CN',
  fallbackLocale: 'en-US',
  missingWarn: false,
  fallbackWarn: false,
  messages: { 'zh-CN': zhCN, 'en-US': enUS },
  missing: (locale, key) => {
    if (import.meta.env.DEV) {
      const id = `${locale}:${key}`
      if (!missingSeen.has(id)) {
        missingSeen.add(id)
        console.warn(`[i18n] missing key "${key}" for locale "${locale}"`)
      }
    }
  }
})
