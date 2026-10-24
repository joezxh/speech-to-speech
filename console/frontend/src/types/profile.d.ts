import type { Values } from '@/utils/draft-patch'

export interface DraftResponse {
  profile: string
  baseVersion: number | null
  draft: Values
  /** 服务端判定为密钥的键（B5）；值一定已是 `***`。 */
  masked: string[]
  updatedAt: string | null
  updatedBy: string
}

export interface ValidationResult {
  ok: boolean
  /** `structural` = 运行时包不在，只校验了结构（§11.2）。 */
  mode: 'runtime' | 'structural'
  resolvedPipelines: string[]
  expectedPoolSize: number | null
  warnings: unknown[]
}

export interface DraftSaveResponse {
  draft: Values
  baseVersion: number | null
  /** 因为回传 `***` 而被忽略的键，UI 可以提示「密钥未变」。 */
  skippedMasked: string[]
  validation: ValidationResult
  auditId: string
}

export interface DiscardResponse {
  discarded: boolean
  revertedTo: string
  auditId: string
}

export interface VersionRow {
  version: number
  status: string
  author: string
  note: string | null
  createdAt: string | null
  durationS: number | null
  rolledBackTo: number | null
}

/** A.8：`fields` 是字段名清单，不是值。 */
export interface AuditRow {
  auditId: string
  at: string | null
  actor: string
  role: string
  action: string
  version: number | null
  fields: string[]
  result: string
  errorCode: string | null
  durationS: number | null
  requestId: string
}
