// views/machines.viewmodel.ts — 机器页视图模型（Task 12，可测纯函数）。
export interface WorkloadRow {
  kind: string
  engine: string
  model: string
  port: number | null
  listen: string
  publicAddr: string
  vramGb: number | null
  healthPath: string
  healthIntervalS: number
  note: string
}

export interface MachineRow {
  machineId: string
  clusterId: string
  profile: string | null
  addr: string
  role: string
  gpu: string
  gpuTotalGb: number | null
  version: string
  state: string
  registryMode: string
  agentVersion: string
  protocolVersion: number | null
  lastSeen: string | null
  workloads: WorkloadRow[]
}

export interface TestStepIn {
  key: string
  label: string
  state: 'pass' | 'pending' | 'fail'
  detail?: Record<string, unknown>
}

export interface TestStepView {
  key: string
  label: string
  state: 'ok' | 'running' | 'fail'
}

export function filterMachines(rows: MachineRow[], q: string): MachineRow[] {
  const needle = q.trim().toLowerCase()
  if (!needle) return rows
  return rows.filter(
    (row) => row.machineId.toLowerCase().includes(needle) || row.addr.toLowerCase().includes(needle)
  )
}

export function vramSummary(
  rows: WorkloadRow[],
  machineTotalGb: number | null
): { usedGb: number; totalGb: number; pct: number } {
  const usedGb = Math.round(rows.reduce((sum, w) => sum + (w.vramGb ?? 0), 0) * 10) / 10
  const totalGb = machineTotalGb ?? 0
  const pct = totalGb > 0 ? Math.round((usedGb / totalGb) * 1000) / 10 : 0
  return { usedGb, totalGb, pct }
}

export function workloadTags(rows: WorkloadRow[]): { kind: string; count: number }[] {
  const counts = new Map<string, number>()
  for (const row of rows) counts.set(row.kind, (counts.get(row.kind) ?? 0) + 1)
  return [...counts.entries()].map(([kind, count]) => ({ kind, count }))
}

/** 后端 pass/pending/fail → 面板 ok/running/fail（三步测试的点色状态机）。 */
export function testStepsToView(steps: TestStepIn[]): TestStepView[] {
  return steps.map((step) => ({
    key: step.key,
    label: step.label,
    state: step.state === 'pass' ? 'ok' : step.state === 'fail' ? 'fail' : 'running'
  }))
}
