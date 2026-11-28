import { api } from './client'

export interface MachineParamRow {
  key: string
  expected: string | null
  actual: string | null
  drift: boolean
  source: string
  effect: string
  exposure: string
  risk: string
  anchor: string
  // 目录元数据（config_view 补齐，供部署页参数表与模板面板/智能设置共用）。
  default?: unknown
  what?: string
  type?: string
  choices?: string[]
  scope?: string
  impact?: string
  changeCost?: string
  sourceRef?: string
  draft?: string | null
}

export const machineConfigApi = {
  view: (machineId: string) => api.get<{ rows: MachineParamRow[] }>(`/machines/${machineId}/config`),
  drift: (machineId: string) => api.get<{ drift_count: number; rows: MachineParamRow[] }>(`/machines/${machineId}/drift`),
  draft: (machineId: string) => api.get<{ version: number; values: Record<string, string> }>(`/machines/${machineId}/draft`),
  putDraft: (machineId: string, patch: Record<string, string>, baseVersion: number) =>
    api.put(`/machines/${machineId}/draft`, { patch, base_version: baseVersion }),
  clearDraft: (machineId: string) => api.delete(`/machines/${machineId}/draft`),
  deploy: (machineId: string, mode: 'push' | 'rollback', confirmWord = '', rows?: string[]) =>
    api.post(`/machines/${machineId}/deploy`, { mode, rows, confirm_word: confirmWord }),
}
