/**
 * A.14 的每一行文案都在这里决定，而不是散在模板里。
 *
 * 这个面板的全部价值是「分得清 0 与不知道」：所以取不到的字段一律渲染成
 * `不可用 · <理由码>`，**不**渲染成 `0 MB` / `0 ms` / `—`。理由码由服务端给出
 * （`reasons.<字段>`），前端只负责把它和字段绑在一起，不自己判断「大概是多少」。
 */

import { DASH } from './format'

import type { GpuInfo, RuntimeReason, RuntimeStage, RuntimeStageName } from '@/types/runtime'

export const STAGE_LABEL: Record<RuntimeStageName, string> = {
  vad: 'VAD',
  stt: 'STT',
  llm: 'LLM',
  tts: 'TTS'
}

/** `不可用 · queue_depth_not_exposed`：码必须跟着走，否则运维要猜。 */
export function unavailable(reason?: RuntimeReason): string {
  return `不可用 · ${reason ?? 'unknown'}`
}

export function loadLabel(loaded: boolean): 'loaded' | 'not loaded' {
  return loaded ? 'loaded' : 'not loaded'
}

/** 模型名取不到时退回加载理由，而不是留空。 */
export function modelText(stage: RuntimeStage): string {
  return stage.modelName ?? unavailable(stage.reasons.loaded)
}

export function percentText(percent: number | null): string {
  return percent === null ? DASH : `${percent}%`
}

export function vramText(stage: RuntimeStage): string {
  if (stage.vram.usedMb === null) return unavailable(stage.reasons.vram)
  return `${stage.vram.usedMb} MB · ${percentText(stage.vram.percent)}`
}

export function busyText(stage: RuntimeStage): string {
  if (stage.busy.inUse === null) return unavailable(stage.reasons.busy)
  const size = stage.busy.size ?? DASH
  return `${stage.busy.inUse} / ${size} ${stage.busy.occupied ? '占用中' : '空闲'}`
}

export function queueText(stage: RuntimeStage): string {
  if (stage.busy.queueDepth === null) return unavailable(stage.reasons.queueDepth)
  return String(stage.busy.queueDepth)
}

export function firstByteText(stage: RuntimeStage): string {
  const value = stage.latency.firstByteMs
  return value === null ? unavailable(stage.reasons.firstByte) : `${value} ms`
}

/** `420 / 980 ms`；`p95` 取不到就整行不可用——半行数字比没有更误导。 */
export function latencyText(stage: RuntimeStage): string {
  const { p50Ms, p95Ms } = stage.latency
  if (p50Ms === null || p95Ms === null) return unavailable(stage.reasons.latency)
  return `${p50Ms} / ${p95Ms} ms`
}

export function gpuHeadline(gpu: GpuInfo | null): string {
  if (!gpu) return 'GPU 状态未知'
  if (!gpu.available) return `GPU 不可用 · ${gpu.reason ?? 'nvidia_smi_missing'}`
  const name = gpu.name ?? 'GPU'
  const used = gpu.usedMb ?? null
  const total = gpu.totalMb ?? null
  if (used === null || total === null) return `${name} · ${unavailable('nvidia_smi_missing')}`
  return `${name} · ${used} / ${total} MB · ${percentText(gpu.percent ?? null)}`
}
