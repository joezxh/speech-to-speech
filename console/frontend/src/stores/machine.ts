// stores/machine.ts — 机器管理（M1–M9）的 pinia store（Task 12）。
import { defineStore } from 'pinia'

import {
  autoRegister,
  createMachine,
  deleteMachine,
  getWorkloads,
  listMachines,
  putWorkloads,
  registerTest,
  updateMachine,
  type MachineDetail,
  type RegisterTestResult
} from '@/api/machines'
import type { WorkloadRow } from '@/views/machines.viewmodel'

export const useMachineStore = defineStore('machine', {
  state: () => ({
    machines: [] as MachineDetail[],
    loading: false,
    error: '' as string,
    lastTest: null as RegisterTestResult | null,
    lastRegisterCode: '' as string
  }),
  getters: {
    byId: (state) => (id: string): MachineDetail | undefined =>
      state.machines.find((m) => m.machineId === id)
  },
  actions: {
    async fetch(cluster?: string): Promise<void> {
      this.loading = true
      this.error = ''
      try {
        const payload = await listMachines(cluster)
        this.machines = payload.machines
      } catch {
        this.error = 'machines.listFailed'
      } finally {
        this.loading = false
      }
    },
    async create(payload: {
      machineId: string
      addr?: string
      role?: string
      gpu?: string
      gpuTotalGb?: number | null
      platform?: string
      driver?: string
      clusterId?: string
      profile?: string | null
    }): Promise<string> {
      const created = await createMachine(payload)
      this.lastRegisterCode = created.registerCode
      await this.fetch()
      return created.registerCode
    },
    async update(id: string, payload: Partial<MachineDetail>): Promise<void> {
      await updateMachine(id, payload)
      await this.fetch()
    },
    async remove(id: string): Promise<void> {
      await deleteMachine(id)
      await this.fetch()
    },
    async saveWorkloads(id: string, workloads: WorkloadRow[]): Promise<void> {
      await putWorkloads(id, workloads)
      await this.fetch()
    },
    async loadWorkloads(id: string): Promise<WorkloadRow[]> {
      return (await getWorkloads(id)).workloads
    },
    async runRegisterTest(payload: {
      machineId: string
      addr?: string
      clusterId?: string
      simulate?: boolean
    }): Promise<RegisterTestResult> {
      this.lastTest = await registerTest(payload)
      await this.fetch()
      return this.lastTest
    },
    async acceptAutoRegister(payload: {
      clusterId?: string
      addr?: string
    }): Promise<{ machineId: string; registerCode: string }> {
      const accepted = await autoRegister(payload)
      await this.fetch()
      return accepted
    }
  }
})
