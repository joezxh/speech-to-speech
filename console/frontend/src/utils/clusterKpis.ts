import type { ClusterRow, InstancesSummary } from '@/types/api'
import { DASH } from '@/utils/format'

/**
 * KPI 四卡的派生（原型 renderOverview 顶部卡片）。summary 缺席（legacy 直连）
 * 或窗口无样本（error_rate_5m === null）时按 spec 口径④渲染 DASH，绝不伪造 0。
 *
 * `sub` 保留原始数值（纯函数、不依赖 i18n）；`subKey` 指向 overview.kpi.sub.*
 * 文案键，由 OverviewView 用 t() 渲染成原型那种带标签的子文案
 * （「在线机器 N」/「活跃会话: N」/「主要错误来源: …」）。
 */
export interface ClusterKpi {
  key: 'machines' | 'instances' | 'sessions' | 'errorRate'
  primary: string
  sub: string
  subKey: 'machinesOnline' | 'activeSessions' | 'stickyHit' | 'topError' | 'noSamples'
  subParams: Record<string, string | number>
  tone: 'ok' | 'warn' | 'muted'
}

const num = (value: number | null | undefined): string =>
  typeof value === 'number' && Number.isFinite(value) ? String(value) : DASH

export function clusterKpis(row: ClusterRow | null, summary: InstancesSummary | null): ClusterKpi[] {
  const online = summary?.machines_online ?? row?.machines_online
  const machinesPrimary = `${num(online)} / ${num(summary?.machines_total ?? row?.machines_total)}`
  const sessions = summary?.slots_in_use
  const rate = summary?.error_rate_5m
  const hasRate = typeof rate === 'number' && Number.isFinite(rate)
  const errorSource = hasRate ? summary?.top_error_instance || DASH : DASH

  return [
    {
      key: 'machines',
      primary: machinesPrimary,
      sub: num(online),
      subKey: 'machinesOnline',
      subParams: { n: num(online) },
      tone: (row?.healthy ?? true) ? 'ok' : 'warn'
    },
    {
      key: 'instances',
      primary: num(summary?.instances_total ?? row?.instances_total),
      sub: num(sessions),
      subKey: 'activeSessions',
      subParams: { n: num(sessions) },
      tone: 'ok'
    },
    {
      key: 'sessions',
      primary: num(sessions),
      // 命中率后端本期不提供（spec §4.4）：子文案渲染「待 S3 交付」占位，不伪造数值。
      sub: num(summary?.slots_free),
      subKey: 'stickyHit',
      subParams: {},
      tone: 'ok'
    },
    {
      key: 'errorRate',
      primary: hasRate ? `${(rate * 100).toFixed(1)}%` : DASH,
      sub: errorSource,
      subKey: hasRate ? 'topError' : 'noSamples',
      subParams: hasRate ? { source: errorSource } : {},
      tone: !hasRate ? 'muted' : rate > 0 ? 'warn' : 'ok'
    }
  ]
}
