import { readLocale, saveLocale } from '@/utils/storage'

export type Locale = 'zh-CN' | 'en-US'
export const SUPPORTED_LOCALES: readonly Locale[] = ['zh-CN', 'en-US']

export function detectLocale(): Locale {
  const stored = readLocale()
  if (stored) return stored
  const lang = (typeof navigator !== 'undefined' ? navigator.language : 'zh-CN') ?? 'zh-CN'
  return lang.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en-US'
}

export { saveLocale }
