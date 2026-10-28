import i18n from '@/i18n'

/**
 * Machine code → human sentence. The backend sends `code` for exactly this
 * purpose (A.0): `message` is English, may quote an input value, and is not
 * something the UI is allowed to render. The sentences live in the i18n catalog
 * (`errors.*` / `alerts.*`) so one source drives both languages (spec §8).
 */

/** snake_case machine code → camelCase i18n key segment. */
function camel(code: string): string {
  return code.replace(/_+$/, '').replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase())
}

/**
 * `/instances` alerts are machine codes too (A.10), kept apart from error codes
 * because one says "your action failed" and the other "the system is degraded".
 * An unknown code falls back to the raw code rather than swallowing the alert.
 */
export function describeAlert(code: string): string {
  const key = `alerts.${camel(code)}`
  return i18n.global.te(key) ? i18n.global.t(key) : code
}

export function translate(code: string): string {
  const key = `errors.${camel(code)}`
  return i18n.global.te(key) ? i18n.global.t(key) : i18n.global.t('errors.fallback')
}

/**
 * A body-less failure (proxy error page, connection reset) still has to become
 * something the user can read, so the status code is turned into one of our own
 * codes. These three plus `unknown` are the only codes the frontend invents.
 */
export function fallbackCode(status?: number): string {
  switch (status) {
    case 403:
      return 'forbidden'
    case 404:
      return 'not_found'
    case 409:
      return 'version_conflict'
    case 429:
      return 'too_many_attempts'
    case 503:
      return 'db_unavailable'
    default:
      return 'network_error'
  }
}
