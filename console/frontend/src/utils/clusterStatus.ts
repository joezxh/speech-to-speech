import type { ClusterRow } from '@/types/api'

/**
 * 集群状态四态（原型 clusterRows 的 statusTag(c.state)：ok / warn / draining / bad）。
 * 后端 ClusterRow 只给 healthy 布尔与机器计数，这里按真实数据派生，不引入新字段：
 *   · 空集群（0 机器）              → muted（spec §6：状态列 tag 灰）
 *   · 健康且机器全在线              → ok
 *   · 健康但部分机器离线            → warn（降级）
 *   · 不健康但仍有在线机器          → draining（排空中）
 *   · 不健康且无在线机器            → bad（故障）
 */
export type ClusterStatus = 'ok' | 'warn' | 'draining' | 'bad' | 'muted'

export function clusterStatus(row: ClusterRow | null | undefined): ClusterStatus {
  if (!row) return 'muted'
  if (row.machines_total <= 0) return 'muted'
  if (row.healthy) return row.machines_online >= row.machines_total ? 'ok' : 'warn'
  return row.machines_online > 0 ? 'draining' : 'bad'
}
