/** 对话示波页纯视图模型（Task 28，光球五态/气泡滚动/工具行）。 */

export type VoiceState = 'connected' | 'listening' | 'thinking' | 'speaking' | 'connecting'

export type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'connecting'

export function orbState(s: VoiceState): OrbState {
  const map: Record<VoiceState, OrbState> = {
    connected: 'idle',
    listening: 'listening',
    thinking: 'thinking',
    speaking: 'speaking',
    connecting: 'connecting',
  }
  return map[s] ?? 'idle'
}

export function bubblesScroll(_to: number, atBottom: boolean): boolean {
  // 只有用户钉在底部时才自动滚；用户上翻阅读历史时不抢滚动。
  return atBottom
}

export interface ToolCfg {
  name: string
  description: string
}

export interface ToolRow extends ToolCfg {
  enabled: boolean
}

export function toolRows(tools: ToolCfg[], enabled: Set<string>): ToolRow[] {
  return tools
    .filter((tool) => enabled.has(tool.name))
    .map((tool) => ({ ...tool, enabled: true }))
}
