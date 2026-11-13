import type { ClusterRow, InstancesSummary } from '@/types/api'
import { DASH } from '@/utils/format'

/**
 * KPI 四卡的派生（原型 renderOverview 顶部卡片）。summary 缺席（legacy 直连）
 * 或窗口无样本（error_rate_5m === null）时按 spec 口径④渲染 DASH，绝不伪造 0。
 */
export interface ClusterKpi {
  key: 'machines' | 'instances' | 'sessions' | 'errorRate'
  primary: string
  sub: string
  tone: 'ok' | 'warn' | 'muted'
}

const num = (value: number | null | undefined): string =>
  typeof value === 'number' && Number.isFinite(value) ? String(value) : DASH

export function clusterKpis(row: ClusterRow | null, summary: InstancesSummary | null): ClusterKpi[] {
  const machinesPrimary = `${num(summary?.machines_online ?? row?.machines_online)} / ${num(
    summary?.machines_total ?? row?.machines_total
  )}`
  const rate = summary?.error_rate_5m
  const hasRate = typeof rate === 'number' && Number.isFinite(rate)
  return [
    {
      key: 'machines',
      primary: machinesPrimary,
      sub: '',
      tone: (row?.healthy ?? true) ? 'ok' : 'warn'
    },
    {
      key: 'instances',
      primary: num(summary?.instances_total ?? row?.instances_total),
      sub: num(summary?.online),
      tone: 'ok'
    },
    {
      key: 'sessions',
      primary: num(summary?.slots_in_use),
      sub: num(summary?.slots_free),
      tone: 'ok'
    },
    {
      key: 'errorRate',
      primary: hasRate ? `${(rate * 100).toFixed(1)}%` : DASH,
      sub: hasRate ? summary?.top_error_instance || DASH : DASH,
      tone: !hasRate ? 'muted' : rate > 0 ? 'warn' : 'ok'
    }
  ]
}