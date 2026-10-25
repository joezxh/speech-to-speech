/** A.17's shapes. Every number is nullable: the server says "not measured". */

export type TurnStatus = 'completed' | 'failed' | 'cancelled' | 'incomplete'

export type TurnLatencyReason =
  | 'no_turn_rows'
  | 'index_lag'
  | 'log_missing'
  | 'indexer_never_ran'

export interface TurnLatencyWindow {
  from: string
  to: string
}

export interface TurnLatencyStage {
  p50Ms: number | null
  p95Ms: number | null
}

export interface TurnLatencyE2E extends TurnLatencyStage {
  maxMs: number | null
}

export interface TurnLatencyHold extends TurnLatencyStage {
  /** Rows whose `holdMs` was null. Never averaged in as 0 (§3.9.4). */
  unavailableCount: number
}

export interface TurnLatencyStages {
  stt: TurnLatencyStage
  llm: TurnLatencyStage
  ttsTtfa: TurnLatencyStage
  vadDecision: TurnLatencyStage
  hold: TurnLatencyHold
}

export interface TurnLatencySummary {
  count: number
  completed: number
  failed: number
  cancelled: number
  incomplete: number
  failureRate: number | null
  e2e: TurnLatencyE2E
  stages: TurnLatencyStages
}

export interface TurnLatencyItem {
  loggedAt: string
  responseKey: string
  turnRevision: number
  source: string
  status: string
  smartStatus: string | null
  e2eMs: number | null
  sttMs: number | null
  llmMs: number | null
  ttsTtfaMs: number | null
  vadDecisionMs: number | null
  holdMs: number | null
}

export interface TurnLatencySource {
  file: string
  size: number
  mtime: string | null
}

export interface TurnLatencyIndex {
  lagS: number | null
  ingestedAt: string | null
  sources: TurnLatencySource[]
}

export interface TurnLatencyPage {
  window: TurnLatencyWindow
  summary: TurnLatencySummary
  rows: TurnLatencyItem[]
  truncated: boolean
  index: TurnLatencyIndex
  reasons: Partial<Record<'summary', TurnLatencyReason>>
}
