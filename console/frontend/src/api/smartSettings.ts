import { api } from './client'
import type { MachineParamRow } from './machineConfig'

export interface SmartMachineSummary {
  machineId: string
  platform: string
  driver: string
  gpu: string
  gpuTotalGb: number | null
  state: string
  version: string
}

export interface SmartLogLine {
  ts: string
  level: string
  text: string
}

export interface SmartFetchResult {
  machine: SmartMachineSummary
  params: MachineParamRow[]
  logs: SmartLogLine[]
}

export interface SmartRecommendation {
  key: string
  from: string
  to: string
  reason: string
}

export interface SmartAnalyzeResult {
  summary: string
  /** llm = 模型结论；rules = 规则兜底（前端灰显「应用」，提示人工确认）。 */
  source: 'llm' | 'rules'
  model: string
  recommendations: SmartRecommendation[]
  durationMs: number
  auditId: string
}

export const smartSettingsApi = {
  fetch: (machineId: string) =>
    api.post<SmartFetchResult>('/smart-settings/fetch', { machineId }),
  analyze: (payload: { machineId: string; fault: string; params: Record<string, string>; logs: string[] }) =>
    api.post<SmartAnalyzeResult>('/smart-settings/analyze', payload)
}
