/**
 * A.18 的形状。列表与详情的差别只在详情多几个字段（`trimStartMs` / `refText` /
 * `precompute` …），所以列表类型把所有详情字段标成可选，详情类型再收窄。
 */
export type VoiceSource = 'builtin' | 'clone' | 'design'

/** 四态（§3.11）：只有 `ready` 能被参数页选中。 */
export type VoiceStatus = 'draft' | 'precomputing' | 'ready' | 'failed'

export type PrecomputeStage = 'queued' | 'loading' | 'spk' | 'rvq' | 'done'

/** `errorCode` 四选一（§3.11.2 步骤 5），原样展示，不解析 `message`。 */
export type PrecomputeError = 'model_not_found' | 'audio_too_short' | 'oom_cpu' | 'timeout'

export interface VoiceUsage {
  /** 草稿里出现的 profile 名。 */
  profiles: string[]
  /** 已发布版本里出现的次数（A.18 是计数，不是列表）。 */
  versions: number
}

export interface VoiceRow {
  id: string
  name: string
  source: VoiceSource
  backend: string
  language: string
  status: VoiceStatus
  audioSeconds: number
  createdAt: string
  createdBy: string
  /** 被多少个 profile 的草稿引用（列表列「引用」用它）。 */
  refCount: number
  usedBy: VoiceUsage
  // 以下只在 `GET /voices/{id}` 出现；列表里缺省。
  trimStartMs?: number
  trimEndMs?: number | null
  refText?: string
  instruct?: string
  consentAckAt?: string | null
  retentionDays?: number
  precompute?: {
    stage: PrecomputeStage
    progress: number
    errorCode: PrecomputeError | string | null
  }
}

export interface VoiceBackend {
  backend: string
  stage: string
  /** `false` = B4 目录化后端：列表里可见，但不可绑定、无字段（§3.11.1）。 */
  catalogued: boolean
  sources: VoiceSource[]
  fields: Record<string, string>
  notes: string
}

/** `POST /voices` 的表单。`consent` 由 api 层固定填 `biometric-ack`。 */
export interface CreateVoiceForm {
  name: string
  source: VoiceSource
  backend: string
  language?: string
  refText?: string
  instruct?: string
  retentionDays?: number
  trimStartMs?: number
  trimEndMs?: number
  audio?: Blob | null
}

export interface CreateVoiceResult {
  id: string
  status: VoiceStatus
  jobId: string
}

export interface VoiceFilter {
  backend?: string
  source?: string
  status?: string
  q?: string
  page?: number
  pageSize?: number
}
