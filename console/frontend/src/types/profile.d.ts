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
