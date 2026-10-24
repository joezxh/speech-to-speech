import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'

dayjs.extend(utc)

export const DASH = '—'

/** ISO 8601 UTC in, local wall clock out (A.0). */
export function formatTime(value: string | null | undefined): string {
  if (!value) return DASH
  const at = dayjs(value)
  return at.isValid() ? at.format('YYYY-MM-DD HH:mm:ss') : DASH
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return DASH
  return seconds < 10 ? `${seconds.toFixed(1)}s` : `${Math.round(seconds)}s`
}
