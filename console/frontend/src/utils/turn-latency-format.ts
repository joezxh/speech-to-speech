import { groupThousands } from '@/utils/format'
import type { TurnLatencyReason, TurnLatencyStage } from '@/types/turn-latency'

/**
 * A.17 的三条显示规则全在这几个函数里：
 * 取不到就是「不可用」，不是 0；缺一半也要保留 `x / y` 的形状；理由码要写出来。
 */
export function stageValue(ms: number | null): string {
  return ms == null ? '不可用' : `${groupThousands(ms)} ms`
}

export function stageStats(stage: Pick<TurnLatencyStage, 'p50Ms' | 'p95Ms'>): string {
  return stage.p50Ms == null && stage.p95Ms == null
    ? '不可用'
    : `${stageValue(stage.p50Ms)} / ${stageValue(stage.p95Ms)}`
}

export function failureRateText(rate: number | null): string {
  return rate == null ? '不可用' : `${(rate * 100).toFixed(1)}%`
}

/** 非空窗的理由码：整块聚合写 `不可用 · <code>`，不排一排 0 ms。 */
export function reasonLabel(reason: TurnLatencyReason): string {
  return `不可用 · ${reason}`
}

/** 响应键在表里只留 12 个字符，`title` 给全串（§3.9.4 的明细表）。 */
export function responseKeyShort(key: string): string {
  return key.length > 12 ? key.slice(0, 12) : key
}

/** 顶部那句必须在面板上也原样出现一次（§3.9.4 第 2 条）。 */
export const E2E_NOTE =
  'E2E: estimated speech end to first generated audio, excluding browser playback. Stages overlap and do not add up.'

export function lagText(lagS: number | null): string {
  return lagS == null ? '索引尚未建立' : `索引落后 ${lagS} s`
}
