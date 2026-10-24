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
}
