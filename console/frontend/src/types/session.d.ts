export type SessionScope = 'all' | 'pipeline' | 'session'

export interface SessionUpdateRequest {
  scope: SessionScope
  /** A unit index for `pipeline`, a session id for `session`, `null` for `all`. */
  target?: number | string | null
  session: Record<string, unknown>
}

/** A.9 — `hint` is server-authored copy that *must* reach the operator (§5.4). */
export interface SessionUpdateResult {
  updated: string[]
  failed: Array<{ sessionId: string; error: string }>
  auditId: string
  hint: string
}
