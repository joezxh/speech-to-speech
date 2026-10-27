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
 * 归档里音频大小的读法：字节整数、往上按 1024 进位并保留 1 位小数。
 * 不用 `toLocaleString`——分隔符跟着环境变，同一份数字在两台机器上长得不一样。
 */
export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = Math.max(0, value)
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return unit === 0 ? `${Math.trunc(size)} ${units[unit]}` : `${size.toFixed(1)} ${units[unit]}`
}

/**
 * 千位用普通空格分组（`6 260`）。不走 `toLocaleString`：不同环境的默认
 * 分隔符不一样（窄空格 / 逗号 / 句点），同一份数字在两台机器上会长得不一样。
 */
export function groupThousands(value: number): string {
  return String(Math.trunc(value)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
}
