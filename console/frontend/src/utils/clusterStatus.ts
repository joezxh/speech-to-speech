import type { ClusterRow } from '@/types/api'

/**
 * 集群状态五态（原型 clusterRows 的 statusTag(c.state)：ok / warn / draining / bad）。
 * 后端 ClusterRow 给 healthy 布尔、机器计数与待接入数，这里按真实数据派生：
 *   · 空集群（0 机器）                        → muted（spec §6：状态列 tag 灰）
 *   · 全部机器待接入（agent 未上线）          → muted（待接入 ≠ 故障，用户反馈）
 *   · 健康且机器全在线                        → ok
 *   · 健康但部分机器离线                      → warn（降级）
 *   · 不健康但仍有在线机器                    → draining（排空中）
 *   · 不健康且无在线机器（且无待接入）        → bad（故障）
 */
export type ClusterStatus = 'ok' | 'warn' | 'draining' | 'bad' | 'muted'

export function clusterStatus(row: ClusterRow | null | undefined): ClusterStatus {
  if (!row) return 'muted'
  if (row.machines_total <= 0) return 'muted'
  if (row.healthy) return row.machines_online >= row.machines_total ? 'ok' : 'warn'
  // 无在线机器但存在待接入机器（建档未跑 agent）：灰显「待接入」，不判故障。
  if (row.machines_online <= 0 && (row.machines_pending ?? 0) > 0) return 'muted'
  return row.machines_online > 0 ? 'draining' : 'bad'
}
