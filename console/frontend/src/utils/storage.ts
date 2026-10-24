import type { TokenBundle } from '@/types/api'

const SESSION_KEY = 's2s.console.session'
const PROFILE_KEY = 's2s.console.profile'

export const DEFAULT_PROFILE = 'prod'

/**
 * `sessionStorage`, not `localStorage`: the console is a single-host ops tool
 * that tends to share a browser, and closing the tab should end the session.
 * Nothing else is persisted — a secret typed into a form lives in component
 * state until it is sent.
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
