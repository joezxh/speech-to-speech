/**
 * 四层拓扑的纯布局（原型 topoSVG，spec §5.2-8）：集群 → LB → 机器 → pipeline 实例。
 * 只算坐标与色调档，不碰 DOM、不碰 i18n；渲染在 TopoChart.vue。
 */
export type TopoTone = 'ok' | 'warn' | 'bad' | 'muted'
export type TopoKind = 'cluster' | 'lb' | 'machine' | 'instance'

export interface TopoNode {
  id: string
  kind: TopoKind
  label: string
  x: number
  y: number
  tone: TopoTone
}

export interface TopoEdge {
  from: string
  to: string
}

export interface TopoLayer {
  key: TopoKind
  y: number
  nodes: TopoNode[]
}

export interface TopoInput {
  cluster: string
  machines: Array<{ host: string; online: boolean }>
  instances: Array<{ id: string; status: string; host: string }>
}

export interface TopoLayout {
  width: number
  height: number
  layers: TopoLayer[]
  edges: TopoEdge[]
}

const WIDTH = 900
const HEIGHT = 380
const LAYER_Y: Record<TopoKind, number> = { cluster: 48, lb: 140, machine: 232, instance: 324 }

const toneForInstance = (status: string): TopoTone =>
  status === 'online' ? 'ok' : status === 'degraded' ? 'warn' : 'bad'

/** n 个同层节点在 WIDTH 内等距：第 i 个落在 (i+1)·WIDTH/(n+1)。 */
function spread(kind: TopoKind, items: Array<{ id: string; label: string; tone: TopoTone }>): TopoNode[] {
  if (!items.length) {
    return [{ id: `${kind}:empty`, kind, label: '', x: WIDTH / 2, y: LAYER_Y[kind], tone: 'muted' }]
  }
  const gap = WIDTH / (items.length + 1)
  return items.map((item, i) => ({
    id: item.id,
    kind,
    label: item.label,
    x: gap * (i + 1),
    y: LAYER_Y[kind],
    tone: item.tone
  }))
}

export function layoutTopo(input: TopoInput): TopoLayout {
  const clusterNodes = spread('cluster', [{ id: `cluster:${input.cluster}`, label: input.cluster, tone: 'ok' }])
  const lbNodes = spread('lb', [{ id: 'lb:console', label: 'Console LB', tone: 'ok' }])
  const machineNodes = spread(
    'machine',
    input.machines.map((m) => ({ id: `machine:${m.host}`, label: m.host, tone: m.online ? 'ok' : 'bad' }))
  )
  const instanceNodes = spread(
    'instance',
    input.instances.map((i) => ({ id: `instance:${i.id}`, label: i.id, tone: toneForInstance(i.status) }))
  )

  const edges: TopoEdge[] = [{ from: clusterNodes[0].id, to: lbNodes[0].id }]
  for (const machine of machineNodes) {
    if (machine.id !== 'machine:empty') edges.push({ from: lbNodes[0].id, to: machine.id })
  }
  for (const instance of instanceNodes) {
    if (instance.id === 'instance:empty') continue
    const host = input.instances.find((i) => `instance:${i.id}` === instance.id)?.host
    const machineId = `machine:${host}`
    if (machineNodes.some((n) => n.id === machineId)) edges.push({ from: machineId, to: instance.id })
  }

  return {
    width: WIDTH,
    height: HEIGHT,
    layers: [
      { key: 'cluster', y: LAYER_Y.cluster, nodes: clusterNodes },
      { key: 'lb', y: LAYER_Y.lb, nodes: lbNodes },
      { key: 'machine', y: LAYER_Y.machine, nodes: machineNodes },
      { key: 'instance', y: LAYER_Y.instance, nodes: instanceNodes }
    ],
    edges
  }
}