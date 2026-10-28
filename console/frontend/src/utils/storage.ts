import type { TokenBundle } from '@/types/api'

import type { Locale } from '@/i18n/locale'

const SESSION_KEY = 's2s.console.session'
const PROFILE_KEY = 's2s.console.profile'
const LOCALE_KEY = 's2s.console.locale'

export const DEFAULT_PROFILE = 'prod'

/**
 * `sessionStorage`, not `localStorage`: the console is a single-host ops tool
 * that tends to share a browser, and closing the tab should end the session.
 * The one exception is the UI language: it is a cross-session preference, so it
 * lives in `localStorage` (see `readLocale` / `saveLocale`). The session token
 * and profile stay in `sessionStorage`; a secret typed into a form lives in
 * component state until it is sent.
 */
export function readBundle(): TokenBundle | null {
  const raw = sessionStorage.getItem(SESSION_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as TokenBundle
    return typeof parsed?.accessToken === 'string' && parsed.accessToken ? parsed : null
  } catch {
    return null
  }
}

export function readToken(): string {
  return readBundle()?.accessToken ?? ''
}

export function saveBundle(bundle: TokenBundle): void {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(bundle))
}

export function clearSession(): void {
  sessionStorage.removeItem(SESSION_KEY)
}

export function readProfile(): string {
  return sessionStorage.getItem(PROFILE_KEY) || DEFAULT_PROFILE
}

export function saveProfile(profile: string): void {
  sessionStorage.setItem(PROFILE_KEY, profile)
}

export function readLocale(): Locale | null {
  const v = localStorage.getItem(LOCALE_KEY)
  return v === 'zh-CN' || v === 'en-US' ? v : null
}

export function saveLocale(locale: Locale): void {
  localStorage.setItem(LOCALE_KEY, locale)
}
