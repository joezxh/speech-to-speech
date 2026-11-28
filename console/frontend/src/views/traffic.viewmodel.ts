/** traffic 页的纯视图模型（Task 15，可单测；公式不留在模板里）。 */

import type { InstanceLatencyRow } from '@/api/traffic'

export interface TrendPoint {
  at: string
  input: number
  output: number
  total: number
}

export interface TrafficInstanceRow {
  instance_id: string
  ttft_ms: number | null
  rtf: number | null
  err_rate: number | null
  [key: string]: unknown
}

export function splitBar(input: number, output: number): { aPct: number } {
  const total = input + output
  return { aPct: total > 0 ? Math.round((input / total) * 1000) / 10 : 0 }
}

export function trendPath(points: TrendPoint[], w: number, h: number): {
  line: string
  area: string
  peak: { x: number; y: number }
  last: { x: number; y: number }
} {
  if (!points.length) return { line: '', area: '', peak: { x: 0, y: h }, last: { x: 0, y: h } }
  const max = Math.max(...points.map((p) => p.total), 1)
  const step = points.length > 1 ? w / (points.length - 1) : 0
  const coordinates = points.map((p, index) => ({
    x: Math.round(index * step * 10) / 10,
    y: Math.round((h - (p.total / max) * h) * 10) / 10,
  }))
  const line = coordinates.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x},${c.y}`).join(' ')
  const area = `${line} L${coordinates[coordinates.length - 1].x},${h} L${coordinates[0].x},${h} Z`
  const peakIndex = coordinates.reduce((best, c, i) => (c.y < coordinates[best].y ? i : best), 0)
  return { line, area, peak: coordinates[peakIndex], last: coordinates[coordinates.length - 1] }
}

export function egressRoute(kind: string): 'lb' | 'direct' {
  return kind === 'pipeline' ? 'lb' : 'direct'
}

const DASH = '—'

/** 毫秒展示：null → —（无数据不编 0）。 */
export function formatMs(ms: number | null): string {
  return ms === null || ms === undefined ? DASH : `${ms} ms`
}

/** 0-1 比率展示：null → —，0.025 → 2.5%。 */
export function formatPct(rate: number | null | undefined): string {
  return rate === null || rate === undefined ? DASH : `${(rate * 100).toFixed(1)}%`
}

/** RTF 展示：null → —。 */
export function formatRtf(rtf: number | null | undefined): string {
  return rtf === null || rtf === undefined ? DASH : rtf.toFixed(2)
}

/** 水位/占比条色调：≥85% 变警示（原型 tkBar 口径），null 不告警。 */
export function barTone(pct: number | null | undefined, warnAt = 85): 'ok' | 'warn' {
  return pct !== null && pct !== undefined && pct >= warnAt ? 'warn' : 'ok'
}

/** 窗口 token 数 → 每分钟速率；无窗口秒数 → null。 */
export function ratePerMinute(tokens: number, windowS: number): number | null {
  return windowS > 0 ? Math.round((tokens / windowS) * 60) : null
}

/** 实例负载条宽度：in_use/size，无容量 → 0%。 */
export function loadBarPct(inUse: number | null | undefined, size: number | null | undefined): string {
  if (!size) return '0%'
  return `${Math.round(((inUse ?? 0) / size) * 100)}%`
}

/** 实例表按 instance_id 合并延迟统计；无统计的实例三列给 null。 */
export function mergeInstanceStats<T extends { instance_id: string }>(
  rows: T[],
  stats: InstanceLatencyRow[] | null,
): Array<T & { ttft_ms: number | null; rtf: number | null; err_rate: number | null }> {
  const byId = new Map((stats ?? []).map((row) => [row.instance_id, row]))
  return rows.map((row) => {
    const stat = byId.get(row.instance_id)
    return {
      ...row,
      ttft_ms: stat?.ttft_ms ?? null,
      rtf: stat?.rtf ?? null,
      err_rate: stat?.err_rate ?? null,
    }
  })
}
