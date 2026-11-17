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
  machine_id: string | null  // Task 10：public_addr 绑定的机器，空=未绑定
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
  // Task 5 派生键：legacy 路径不返回，必须保持可选。
  machines_total?: number
  machines_online?: number
  error_rate_5m?: number | null
  top_error_instance?: string | null
}

/** 集群行：字段名与后端 routers/clusters.py `_row_payload` 逐字一致。 */
export interface ClusterRow {
  name: string
  registry: string
  policy: 'least' | 'rr' | 'lat'
  note: string
  machines_total: number
  machines_online: number
  /** 注册了但 agent 未上线（pending_register）的机器数；用于区分「待接入」与「故障」。 */
  machines_pending?: number
  instances_total: number
  healthy: boolean
  updated_at: string
  updated_by: string
}

/** 集群写载荷：POST 全量、PUT 不含 name（name 在路径上）。 */
export interface ClusterWritePayload {
  name: string
  registry: string
  policy: string
  note: string
}

/** 最近事件行：字段名与后端 `/clusters/events` 逐字一致（camelCase）。 */
export interface ClusterEventRow {
  auditId: string
  at: string
  actor: string
  role: string
  action: string
  profile: string
  fields: string[]
  result: 'ok' | 'error'
  errorCode: string
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
