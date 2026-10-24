import { createI18n } from 'vue-i18n'

import zhCN from './zh-CN'

/** Only zh-CN ships now; the mechanism is here so a second locale is a file. */
export default createI18n({
  legacy: false,
  locale: 'zh-CN',
  fallbackLocale: 'zh-CN',
  messages: { 'zh-CN': zhCN }
})
