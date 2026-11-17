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
