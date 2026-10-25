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

/**
 * 千位用普通空格分组（`6 260`）。不走 `toLocaleString`：不同环境的默认
 * 分隔符不一样（窄空格 / 逗号 / 句点），同一份数字在两台机器上会长得不一样。
 */
export function groupThousands(value: number): string {
  return String(Math.trunc(value)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
}
