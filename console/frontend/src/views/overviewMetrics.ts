import type { InstanceSnapshot, StatusSnapshot } from '@/types/api'

export interface OverviewMetric {
  key: string
  value: string | null
  unimpl?: 'S2' | 'S3' | 'none'
}

/** `null` means “拿不到”，视图层据此渲染 DASH；绝不用占位假数据填充。 */
const text = (v: string | number | null | undefined): string | null =>
  v === null || v === undefined || v === '' ? null : String(v)

const count = (v: number | null | undefined): string | null => (v === null || v === undefined ? null : String(v))

const flag = (v: boolean | null | undefined): string | null => (v === null || v === undefined ? null : String(v))

/**
 * Maps the two read-only endpoints (`GET /status`, `GET /instances`) onto the
 * overview KPI grid (spec §10.1). Demo-only metrics that no endpoint can back
 * yet are flagged `unimpl` with the owning subproject — never mocked.
 */
export function overviewMetrics(status: StatusSnapshot, snapshot: InstanceSnapshot): OverviewMetric[] {
  const summary = snapshot.summary

  return [
    // —— cluster totals (registry-derived; absent on the legacy single-instance path)
    { key: 'overview.kpi.pipelineInstances', value: count(summary?.instances_total) },
    { key: 'overview.kpi.online', value: count(summary?.online) },
    { key: 'overview.kpi.degraded', value: count(summary?.degraded) },
    { key: 'overview.kpi.offline', value: count(summary?.offline) },
    { key: 'overview.kpi.draining', value: count(summary?.draining) },
    { key: 'overview.kpi.activeSessions', value: count(summary?.slots_in_use) },
    { key: 'overview.kpi.freeSlots', value: count(summary?.slots_free) },
    { key: 'overview.kpi.totalSlots', value: count(summary?.slots_total) },
    { key: 'overview.kpi.pendingGrants', value: count(summary?.pending_grants) },
    { key: 'overview.kpi.clusterAlerts', value: count(snapshot.alerts?.length ?? 0) },
    // —— release / health (top bar facts, same source as ConsoleLayout)
    { key: 'overview.kpi.catalogCommit', value: text(status.catalogCommit) },
    { key: 'overview.kpi.version', value: count(status.version) },
    { key: 'overview.kpi.status', value: text(status.status) },
    { key: 'overview.kpi.dbHealth', value: text(status.db) },
    { key: 'overview.kpi.pipelineHealth', value: text(status.pipeline) },
    // —— allocator state (P1.3 fields; optional until the backend adds them)
    { key: 'overview.kpi.allocatorMode', value: text(status.allocatorMode) },
    { key: 'overview.kpi.consoleId', value: text(status.consoleId) },
    { key: 'overview.kpi.instancesRegistered', value: count(status.instancesRegistered) },
    { key: 'overview.kpi.seedConfigured', value: flag(status.seedConfigured) },
    { key: 'overview.kpi.secretsConsistent', value: flag(status.secretsConsistent) },
    // —— declared in the demo but backed by nothing yet
    { key: 'overview.unimpl.machines', value: null, unimpl: 'S2' },
    { key: 'overview.unimpl.errorRate', value: null, unimpl: 'S3' },
    { key: 'overview.unimpl.stickiness', value: null, unimpl: 'S3' },
    { key: 'overview.unimpl.p95ttft', value: null, unimpl: 'S3' },
    { key: 'overview.unimpl.training', value: null, unimpl: 'none' },
  ]
}
