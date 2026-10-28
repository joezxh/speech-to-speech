/** The envelope every `/api/v1/*` success response carries (A.0). */
export interface Envelope<T> {
  code: number
  message: string
  data: T
}

/** The envelope every `/api/v1/*` failure carries (A.0). */
export interface ApiErrorBody {
  code: string
  message: string
  detail?: unknown[]
  requestId?: string
}

/** Every paged list endpoint answers with this (A.0). */
export interface Page<T> {
  list: T[]
  total: number
  page: number
  pageSize: number
}

export interface User {
  username: string
  role: 'admin' | 'operator'
}

export interface UserProfile extends User {
  lastLoginAt: string | null
}

export interface TokenBundle {
  accessToken: string
  tokenType: 'bearer'
  expiresIn: number
  refreshToken: string
  user: User
}

/** A.11 — the top bar reads this. */
export interface StatusSnapshot {
  profile: string
  version: number | null
  status: string
  catalogCommit: string
  validatorMode: 'runtime' | 'structural'
  db: 'ok' | 'unavailable'
  pipeline: 'ok' | 'unreachable'
  internalTokenConfigured: boolean
  // P1.3（spec §12）：allocator/seed 状态，与后端 status_service.snapshot 对齐。
  allocatorMode?: string
  instancesRegistered?: number
  seedConfigured?: boolean
  consoleId?: string
  secretsConsistent?: boolean
}

export interface PoolUnit {
  index: number | null
  state: string | null
  sessionId: string | null
}

/** A.10。`pool` 为 `null` 表示探不到，不是「没有 unit」。 */
export interface InstanceSnapshot {
  profile: string
  version: number | null
  container: {
    name: string
    status: string
    startedAt: string | null
    image: string
    pid: number | null
    detail: string
  }
  pool: { size: number; inUse: number; units: PoolUnit[] } | null
  usage: Record<string, unknown> | null
  alerts: string[]
  // 注册表非空才有；单实例 legacy 直连路径不返回这两键，故可选。
  summary?: InstancesSummary
  instances?: InstanceRow[]
}

/** 机器级状态：由 registry 巡检推导，与 unit 级 (idle/active/draining/stuck) 绝不混用。 */
export type InstanceStatus = 'unknown' | 'online' | 'degraded' | 'offline' | 'draining'

/** 字段名与后端 instances_service._collect_registry 逐字一致（snake_case）。 */
export interface InstanceRow {
  instance_id: string
  base_url: string
  status: InstanceStatus
  weight: number
  enabled: boolean
  drain_requested: boolean
  size: number | null
  in_use: number | null
  free: number | null
  stuck: number | null
  probe_ms: number | null
  p95_probe_ms: number | null
  units: PoolUnit[]
  last_error: string
  observed_by: string
  declared_mismatch: boolean
}

export interface InstancesSummary {
  instances_total: number
  online: number
  offline: number
  degraded: number
  draining: number
  slots_total: number
  slots_in_use: number
  slots_free: number
  pending_grants: number
}

/** 字段名与后端 schemas.instance.metric_point 逐字一致（camelCase）。 */
export interface InstanceMetricPoint {
  observedAt: string
  observedBy: string
  kind: 'sample' | 'state_change'
  status: string
  size: number | null
  inUse: number | null
  free: number | null
  stuck: number | null
  probeMs: number | null
  allocOk: number
  allocFailNoInstance: number
  allocFailInstance503: number
  evictCount: number
  recoverCount: number
}
