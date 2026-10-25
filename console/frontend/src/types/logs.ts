/**
 * A.15 / A.16 shapes. Field names are the contract's, verbatim; the four
 * analysis blocks are spelled out so a stray extra key fails the type check
 * rather than rendering as an empty cell.
 */

export type LogLevel = 'ERROR' | 'WARN' | 'INFO'
export type LogProcess = 'console' | 'pipeline'

export interface LogLine {
  ts: string
  process: string
  stream: string
  level: string
  text: string
  file: string
  offset: number
}

export interface LogSource {
  file: string
  size: number
  mtime: string | null
}

export interface LogScanned {
  files: number
  bytes: number
}

/** A.15's `data`. `nextCursor` is opaque: the client only echoes it back. */
export interface LogPage {
  lines: LogLine[]
  nextCursor: string
  reset: boolean
  truncated: boolean
  scanned: LogScanned
  sources: LogSource[]
}

export interface LogQuery {
  process: string[]
  level: string[]
  from: string
  to: string
  q: string
  after?: string
  limit?: number
}

export interface LogSent {
  lines: number
  estimatedTokens: number
  truncated: boolean
  droppedLines: number
  turnRows: number
}

export interface LogError {
  signature: string
  count: number
  firstSeen: string
  lastSeen: string
  level: string
  sample: string
}

export interface LogCritical {
  signature: string
  impact: string
  rationale: string
  evidence: string
}

export interface LogRootCause {
  hypothesis: string
  /** 0–1；`confidenceText()` 把它翻成高 / 中 / 低。 */
  confidence: number
  evidence: string
}

export interface LogAction {
  title: string
  detail: string
  expectedEffect: string
  risk: string
}

export interface LogAnalysisResult {
  errors: LogError[]
  critical: LogCritical[]
  rootCauses: LogRootCause[]
  actions: LogAction[]
}

/** A.16's `data`. */
export interface LogAnalysis {
  analysisId: string
  model: string
  durationMs: number
  sent: LogSent
  result: LogAnalysisResult
  auditId: string
}

export interface AnalyzeBody {
  from: string
  to: string
  process?: string[]
  level?: string[]
  q?: string
  maxLines?: number
  includeTurnLatency?: boolean
}
