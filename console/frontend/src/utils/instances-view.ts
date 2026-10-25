import type { InstanceMetricPoint, InstanceRow } from '@/types/api'

const COLORS: Record<string, 'default' | 'green' | 'orange' | 'red' | 'blue'> = {
  unknown: 'default',
  online: 'green',
  degraded: 'orange',
  offline: 'red',
  draining: 'blue',
}

export const statusColor = (status: string) => COLORS[status] ?? 'default'

export const statusLabelKey = (status: string) => `instances.status.${status}`

/**
 * 跨 console 取数规则：同一秒桶内只留 observedAt 最新的一行，不累加（spec §10）。
 * 两台 console 指向同一批实例时，同一实例同一时刻会有多行重复采样，直接求和会把
 * 边沿计数与槽位数放大 ×N，所以这里按秒粒度去重，取时间戳最大的那行。
 */
export function dedupeByLatestObserver(points: InstanceMetricPoint[]): InstanceMetricPoint[] {
  const byBucket = new Map<string, InstanceMetricPoint>()
  for (const point of points) {
    const bucket = point.observedAt.slice(0, 19) // 秒粒度：两台 console 同时刻的重复采样归同一桶
    const kept = byBucket.get(bucket)
    // 同桶内取时间戳最新的一行；用 Date 解析而非字符串比较，兼容带/不带毫秒与时区后缀的 ISO。
    if (!kept || new Date(kept.observedAt).getTime() < new Date(point.observedAt).getTime()) {
      byBucket.set(bucket, point)
    }
  }
  return [...byBucket.values()].sort((a, b) => a.observedAt.localeCompare(b.observedAt))
}

export const capacityPercent = (row: InstanceRow): number =>
  row.size && row.size > 0 ? Math.round(((row.in_use ?? 0) / row.size) * 100) : 0
