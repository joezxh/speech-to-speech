/** 五步音色向导视图模型（Task 27，跳过逻辑是核心，spec §4.7）。
 * 界面文案用「声纹嵌入」，不出现 x-vector。 */

export type WizardSource = 'builtin' | 'clone' | 'design'

export type WizardStep = 'source' | 'record' | 'trim' | 'voiceprint' | 'naming'

export interface WizardState {
  source: WizardSource
  name: string
  audioBars: number[]
  pending: boolean
  window: [number, number]
}

export function stepsFor(source: WizardSource): WizardStep[] {
  if (source === 'builtin') return ['source', 'naming']
  if (source === 'design') return ['source', 'record', 'voiceprint', 'naming']
  return ['source', 'record', 'trim', 'voiceprint', 'naming']
}

export interface Bar {
  value: number
  highlight: boolean
}

export function trimWindow(bars: number[], startMs: number, endMs: number): { bars: Bar[]; window: [number, number] } {
  // 假设整段音频映射到 48 柱：窗口内柱高亮。
  const total = bars.length || 1
  const [lo, hi] = startMs <= endMs ? [startMs, endMs] : [endMs, startMs]
  const from = Math.floor((lo / Math.max(hi, 1)) * total)
  const to = Math.ceil((hi / Math.max(hi, 1)) * total)
  return {
    bars: bars.map((value, index) => ({ value, highlight: index >= from && index < Math.max(to, from + 1) })),
    window: [lo, hi],
  }
}

export function canAdvance(step: WizardStep, s: WizardState): boolean {
  if (step === 'voiceprint') return !s.pending
  if (step === 'naming') return s.name.trim().length > 0
  if (step === 'trim') return s.window[1] > s.window[0]
  return true
}
