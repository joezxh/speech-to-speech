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
  // agent 从生效配置采集的模型与全部参数（密钥已掩码）。
  params?: Record<string, unknown>
}

export function workloadParamEntries(
  params: Record<string, unknown> | undefined
): Array<{ key: string; value: string }> {
  if (!params) return []
  return Object.entries(params)
    .map(([key, value]) => ({
      key,
      value: typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value)
    }))
    .sort((a, b) => a.key.localeCompare(b.key))
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

export interface ClusterOption {
  value: string
  label: string
}

/** 机器表单的集群下拉选项：集群表全量 + 当前值兜底（软关联：旧值必须可选）。 */
export function clusterOptions(
  clusters: Array<{ name: string }>,
  current: string
): ClusterOption[] {
  const values = clusters.map((cluster) => cluster.name)
  if (current && !values.includes(current)) values.push(current)
  return values.map((value) => ({ value, label: value }))
}

export interface MachineCommandView {
  commandId: string
  machineId: string
  kind: string
  status: string
  payload: Record<string, unknown>
  result: Record<string, unknown> | null
  error: string
  expiresAt: string | null
  dispatchedAt: string | null
  finishedAt: string | null
  createdAt: string | null
}

export type CommandKind = 'drain' | 'resume' | 'reboot' | 'recover' | 'health_check'

/** 原型机器行动作：排空中→恢复，不可达/故障→拉起，其他→排空+重启。 */
export function commandActions(
  state: string,
  activeKinds: string[]
): Array<{ kind: CommandKind; labelKey: string; disabled: boolean }> {
  const kinds: CommandKind[] =
    state === 'draining'
      ? ['resume']
      : state === 'unreachable' || state === 'bad' || state === 'offline'
        ? ['recover']
        : ['drain', 'reboot']
  return kinds.map((kind) => ({
    kind,
    labelKey: `machines.action.${kind}`,
    disabled: activeKinds.includes(kind)
  }))
}

/** agent 端 _service_matches 接受 kind 或 kind:port，这里生成同一个稳定 ID。 */
export function serviceIdOf(workload: WorkloadRow): string {
  return workload.port == null ? workload.kind : `${workload.kind}:${workload.port}`
}

export function latestHealth(
  commands: MachineCommandView[],
  serviceId: string
): MachineCommandView | undefined {
  return commands
    .filter(
      (command) =>
        command.kind === 'health_check' && command.payload?.service_id === serviceId
    )
    .sort((a, b) => String(b.createdAt ?? '').localeCompare(String(a.createdAt ?? '')))[0]
}

/** 检查结果四态：无命令=unknown，进行中=checking，真结果=ok/bad。 */
export function healthState(
  command: MachineCommandView | undefined
): 'unknown' | 'checking' | 'ok' | 'bad' {
  if (!command) return 'unknown'
  if (command.status === 'pending' || command.status === 'dispatched') return 'checking'
  if (command.result?.reachable === true && command.status === 'succeeded') return 'ok'
  if (command.result?.reachable === false || command.status === 'failed') return 'bad'
  return 'unknown'
}

/** 后端 pass/pending/fail → 面板 ok/running/fail（三步测试的点色状态机）。 */
export function testStepsToView(steps: TestStepIn[]): TestStepView[] {
  return steps.map((step) => ({
    key: step.key,
    label: step.label,
    state: step.state === 'pass' ? 'ok' : step.state === 'fail' ? 'fail' : 'running'
  }))
}
