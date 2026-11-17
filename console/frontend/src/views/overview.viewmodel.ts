/** 集群总览页纯视图模型（Task 29，KPI/拓扑/最近事件真值）。 */

export interface Machine {
  machineId: string
  state: string
  role: string
  gpu: string
  gpuTotalGb: number | null
  version: string
}

export interface Instance {
  instance_id: string
  base_url: string
  machine_id: string | null
  status: string
}

export interface LbStats {
  sticky_hit_rate: number | null
  rules: Array<Record<string, unknown>>
}

export interface AuditRow {
  id: number
  at: string
  actor: string
  action: string
  category: string
  profile: string
}

export interface Kpi {
  key: string
  label: string
  value: string
}

export function overviewKpis(machines: Machine[], instances: Instance[], s: LbStats, _events: AuditRow[]): Kpi[] {
  const online = machines.filter((m) => m.state === 'online').length
  const healthy = instances.filter((i) => i.status === 'online').length
  return [
    { key: 'machines', label: '在线机器', value: `${online}/${machines.length}` },
    { key: 'instances', label: '健康实例', value: `${healthy}/${instances.length}` },
    {
      key: 'hitRate',
      label: '粘性命中率',
      // 无路由日志时不可得（不是 0，不是假数据）。
      value: s.sticky_hit_rate === null ? '不可得' : `${Math.round(s.sticky_hit_rate * 100)}%`,
    },
    { key: 'rules', label: '路由规则', value: String(s.rules.length) },
  ]
}

export interface TopoRow {
  machine_id: string | null
  machine: Machine | null
  instances: Instance[]
}

export function topoRows(machines: Machine[], instances: Instance[]): TopoRow[] {
  const rows: TopoRow[] = machines.map((machine) => ({
    machine_id: machine.machineId,
    machine,
    instances: instances.filter((i) => i.machine_id === machine.machineId),
  }))
  const boundIds = new Set(machines.map((m) => m.machineId))
  const unbound = instances.filter((i) => !i.machine_id || !boundIds.has(i.machine_id))
  if (unbound.length) {
    rows.push({ machine_id: null, machine: null, instances: unbound })
  }
  return rows
}

export interface EventRow extends AuditRow {}

export function eventRows(events: AuditRow[]): AuditRow[] {
  return [...events]
    .sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0))
    .slice(0, 8)
}
