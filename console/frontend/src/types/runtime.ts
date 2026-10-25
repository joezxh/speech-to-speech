/**
 * A.14's model runtime snapshot. Field names are the contract's, verbatim —
 * the backend and these types are the only two places they are spelled.
 */

export type RuntimeStageName = 'vad' | 'stt' | 'llm' | 'tts'

/** Every code A.14 allows. A reason is never free text. */
export type RuntimeReason =
  | 'config_unreadable'
  | 'pipeline_stopped'
  | 'no_metrics_window'
  | 'nvidia_smi_missing'
  | 'vram_not_attributable'
  | 'pool_unreachable'
  | 'queue_depth_not_exposed'
  | 'first_byte_not_instrumented'
  | 'not_applicable'

/** The fields a reason may be attached to (A.14's invariant). */
export type RuntimeReasonKey =
  | 'loaded'
  | 'vram'
  | 'busy'
  | 'queueDepth'
  | 'firstByte'
  | 'latency'

export interface RuntimeStage {
  stage: RuntimeStageName
  modelName: string | null
  backend: string | null
  loaded: boolean
  vram: { usedMb: number | null; percent: number | null }
  busy: { inUse: number | null; size: number | null; occupied: boolean; queueDepth: number | null }
  latency: {
    firstByteMs: number | null
    processMs: number | null
    p50Ms: number | null
    p95Ms: number | null
  }
  reasons: Partial<Record<RuntimeReasonKey, RuntimeReason>>
}

export interface GpuInfo {
  available: boolean
  name?: string | null
  totalMb?: number | null
  usedMb?: number | null
  percent?: number | null
  reason?: RuntimeReason
}

/** A.14 的 `alerts`：与 `/instances` 的 `alerts` 语义不同，分开渲染。 */
export type RuntimeAlert = 'pipeline_stopped' | 'vram_pressure' | 'pool_unreachable' | 'runtime_degraded'

export interface RuntimeSnapshot {
  profile: string
  collectedAt: string
  windowS: number
  gpu: GpuInfo
  stages: RuntimeStage[]
  alerts: RuntimeAlert[]
}
