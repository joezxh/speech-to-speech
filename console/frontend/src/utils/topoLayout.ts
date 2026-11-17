/**
 * 拓扑布局（原型 topoSVG 的横向三段：LB → 机器行 → Pipeline 实例 chip）。
 *
 * 与早期「四层纵向等距」实现不同：原型是**左 LB、机器按行垂直堆叠、实例 chip
 * 挂在机器右侧**的横向图，机器盒与实例盒尺寸/坐标都固定。这里只算坐标与色调，
 * 不碰 DOM / i18n；真实元信息由 TopoChart.vue 渲染。
 *
 * 数据来源全部真实：集群名/registry/policy 来自 ClusterRow，会话数来自
 * /instances summary，机器由实例 base_url 的 host 派生，chip 的占用来自
 * InstanceRow.in_use / size，rpm 来自 InstanceRow.rpm_5m（5m 分配窗口真源，
 * 无样本 = null）；没有来源的字段（role / ver / util）一律省略。
 */
export type TopoTone = 'ok' | 'warn' | 'draining' | 'bad' | 'muted'

export interface TopoChip {
  id: string
  label: string
  tone: TopoTone
  inUse: number | null
  size: number | null
  /** 每分钟分配尝试数（5m 窗口）；无样本 = null。 */
  rpm: number | null
  x: number
  y: number
}

export interface TopoMachine {
  id: string
  host: string
  tone: TopoTone
  y: number
  instanceCount: number
  onlineCount: number
  chips: TopoChip[]
  active: boolean
  /** param_machine.machine_id（注册机器才有）。 */
  label: string
  /** 负载模型行（kind·model），拓扑盒展示；实例派生的机器为空数组。 */
  models: string[]
}

export interface TopoLb {
  x: number
  y: number
  w: number
  h: number
  cluster: string
  registry: string
  policy: string
  sessions: number | null
}

export interface TopoEdge {
  d: string
  flow: boolean
}

export interface TopoInput {
  cluster: string
  registry: string
  policy: string
  sessions: number | null
  machines: Array<{
    host: string
    online: boolean
    /** param_machine.machine_id（注册机器才有；实例派生的机器为空）。 */
    label?: string
    /** 该机器声明的负载模型（workloads 的 kind·model），拓扑盒上展示。 */
    models?: string[]
  }>
  instances: Array<{
    id: string
    status: string
    host: string
    inUse?: number | null
    size?: number | null
    rpm?: number | null
  }>
}

export interface TopoLayout {
  width: number
  height: number
  lb: TopoLb
  machines: TopoMachine[]
  edges: TopoEdge[]
  empty: boolean
}

/** 原型 topoSVG 的固定几何，勿随意改动。 */
const WIDTH = 980
const LB_X = 40
const LB_W = 180
const LB_H = 76
const MX_X = 300
const MX_W = 200
const MX_H = 64
const CHIP_X0 = 560
const CHIP_GAP = 132
const ROW_Y0 = 26
const ROW_H = 80

const toneForInstance = (status: string): TopoTone =>
  status === 'online'
    ? 'ok'
    : status === 'degraded'
      ? 'warn'
      : status === 'draining'
        ? 'draining'
        : 'bad'

export function layoutTopo(input: TopoInput): TopoLayout {
  const height = Math.max(430, input.machines.length * ROW_H + 30)
  const lbY = Math.round(height / 2 - 38)

  const machines: TopoMachine[] = input.machines.map((machine, i) => {
    const y = ROW_Y0 + i * ROW_H
    const rows = input.instances.filter((instance) => instance.host === machine.host)
    const chips: TopoChip[] = rows.map((instance, j) => ({
      id: `instance:${instance.id}`,
      label: instance.id,
      tone: toneForInstance(instance.status),
      inUse: instance.inUse ?? null,
      size: instance.size ?? null,
      rpm: instance.rpm ?? null,
      x: CHIP_X0 + j * CHIP_GAP,
      y: y + 16
    }))
    return {
      id: `machine:${machine.host}`,
      host: machine.host,
      tone: machine.online ? 'ok' : 'bad',
      y,
      instanceCount: rows.length,
      onlineCount: rows.filter((instance) => instance.status === 'online').length,
      chips,
      // 原型：该机器下任一实例 inUse>0 就把这一行的连线全部点亮为 flow。
      active: rows.some((instance) => (instance.inUse ?? 0) > 0),
      label: machine.label ?? '',
      models: machine.models ?? []
    }
  })

  const edges: TopoEdge[] = []
  for (const machine of machines) {
    const midY = machine.y + MX_H / 2
    edges.push({
      d: `M220 ${lbY + LB_H / 2} C260 ${lbY + LB_H / 2} 260 ${midY} ${MX_X} ${midY}`,
      flow: true
    })
    for (const chip of machine.chips) {
      edges.push({
        d: `M${MX_X + MX_W + 10} ${midY} H${chip.x}`,
        flow: machine.active
      })
    }
  }

  return {
    width: WIDTH,
    height,
    lb: {
      x: LB_X,
      y: lbY,
      w: LB_W,
      h: LB_H,
      cluster: input.cluster,
      registry: input.registry,
      policy: input.policy,
      sessions: input.sessions
    },
    machines,
    edges,
    empty: machines.length === 0
  }
}
