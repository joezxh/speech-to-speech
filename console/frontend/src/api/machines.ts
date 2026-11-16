// api/machines.ts — M1–M9（spec 2026-11-17 §7.2.2）。
import { api } from './client'
import type { MachineRow, TestStepIn, WorkloadRow } from '@/views/machines.viewmodel'

export interface MachineDetail extends MachineRow {
  version: string
  profile: string | null
  gpuTotalGb: number | null
  lastSeen: string | null
  agentVersion: string
  protocolVersion: number | null
  workloadCount: number
  createdAt: string | null
  updatedAt: string | null
  createdBy: string
  updatedBy: string
}

export interface RegisterTestResult {
  steps: TestStepIn[]
  ok: boolean
  // M8 重签/新建时返回；snake_case 是后端 service dict 的原样透出。
  register_code?: string
}

export const listMachines = (cluster?: string): Promise<{ machines: MachineDetail[]; total: number }> =>
  api.get<{ machines: MachineDetail[]; total: number }>('/machines', { params: cluster ? { cluster } : {} })

export const getMachine = (id: string): Promise<MachineDetail> => api.get<MachineDetail>(`/machines/${id}`)

export const createMachine = (payload: {
  machineId: string
  addr?: string
  role?: string
  gpu?: string
  gpuTotalGb?: number | null
  clusterId?: string
  profile?: string | null
}): Promise<{ machine: Record<string, unknown>; registerCode: string }> =>
  api.post<{ machine: Record<string, unknown>; registerCode: string }>('/machines', payload)

export const updateMachine = (id: string, payload: Partial<MachineDetail>): Promise<MachineDetail> =>
  api.put<MachineDetail>(`/machines/${id}`, payload)

export const deleteMachine = (id: string): Promise<void> => api.delete(`/machines/${id}`)

export const getWorkloads = (id: string): Promise<{ workloads: WorkloadRow[] }> =>
  api.get<{ workloads: WorkloadRow[] }>(`/machines/${id}/workloads`)

export const putWorkloads = (id: string, workloads: WorkloadRow[]): Promise<{ workloads: WorkloadRow[] }> =>
  api.put<{ workloads: WorkloadRow[] }>(`/machines/${id}/workloads`, { workloads })

export const registerTest = (payload: {
  machineId: string
  addr?: string
  clusterId?: string
  simulate?: boolean
}): Promise<RegisterTestResult> => api.post<RegisterTestResult>('/machines/register-test', payload)

export const autoRegister = (payload: {
  clusterId?: string
  addr?: string
  machineId?: string | null
}): Promise<{ machineId: string; registerCode: string; state: string }> =>
  api.post<{ machineId: string; registerCode: string; state: string }>('/machines/auto-register', payload)
