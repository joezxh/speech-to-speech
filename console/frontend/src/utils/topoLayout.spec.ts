import { describe, expect, it } from 'vitest'

import { layoutTopo, type TopoInput } from './topoLayout'

const input: TopoInput = {
  cluster: 'default',
  registry: 'consul://h:8500',
  policy: 'least',
  sessions: 9,
  machines: [
    { host: 'host1', online: true },
    { host: 'host2', online: false }
  ],
  instances: [
    { id: 'pipe-a', status: 'online', host: 'host1', inUse: 2, size: 4, rpm: 12 },
    { id: 'pipe-b', status: 'degraded', host: 'host1', inUse: 0, size: 4 },
    { id: 'pipe-c', status: 'offline', host: 'host2', inUse: 0, size: 8 }
  ]
}
const full = layoutTopo(input)

describe('layoutTopo (prototype topoSVG horizontal geometry)', () => {
  it('uses the horizontal LB → machine rows → instance chips geometry', () => {
    expect(full.width).toBe(980)
    expect(full.lb.x).toBe(40)
    expect(full.lb.w).toBe(180)
    expect(full.lb.h).toBe(76)
    expect(full.machines.map((m) => m.y)).toEqual([26, 106])
    expect(full.machines[0].chips.map((c) => c.x)).toEqual([560, 692])
    expect(full.machines[1].chips.map((c) => c.x)).toEqual([560])
  })

  it('carries only real metadata (rpm from alloc counters; no mock role / ver / util)', () => {
    expect(full.lb).toMatchObject({
      cluster: 'default',
      registry: 'consul://h:8500',
      policy: 'least',
      sessions: 9
    })
    expect(full.machines[0].instanceCount).toBe(2)
    expect(full.machines[0].onlineCount).toBe(1)
    expect(full.machines[0].chips[0]).toMatchObject({ label: 'pipe-a', inUse: 2, size: 4, rpm: 12 })
    // 无真源 = null（原型 rpm 是 mock，这里必须来自 5m 分配窗口，缺失不编造）
    expect(full.machines[0].chips[1].rpm).toBeNull()
  })

  it('maps statuses to ok / warn / draining / bad tones', () => {
    expect(full.machines.map((m) => m.tone)).toEqual(['ok', 'bad'])
    expect(full.machines[0].chips.map((c) => c.tone)).toEqual(['ok', 'warn'])
    const draining = layoutTopo({
      ...input,
      instances: [{ id: 'pipe-x', status: 'draining', host: 'host1' }]
    })
    expect(draining.machines[0].chips[0].tone).toBe('draining')
  })

  it('lights LB→machine edges and derives chip flow from real in_use', () => {
    expect(full.edges).toHaveLength(5)
    const lbEdges = full.edges.filter((e) => e.d.startsWith('M220'))
    expect(lbEdges).toHaveLength(2)
    expect(lbEdges.every((e) => e.flow)).toBe(true)
    const chipEdges = full.edges.filter((e) => e.d.startsWith('M510'))
    expect(chipEdges).toHaveLength(3)
    expect(chipEdges.map((e) => e.flow)).toEqual([true, true, false])
  })

  it('keeps an empty cluster renderable with LB only', () => {
    const empty = layoutTopo({ ...input, machines: [], instances: [] })
    expect(empty.empty).toBe(true)
    expect(empty.machines).toEqual([])
    expect(empty.edges).toEqual([])
    expect(empty.height).toBe(430)
  })

  it('grows the canvas with machine rows', () => {
    const many = layoutTopo({
      ...input,
      machines: Array.from({ length: 8 }, (_, i) => ({ host: `h${i}`, online: true })),
      instances: []
    })
    expect(many.height).toBe(8 * 80 + 30)
  })

  it('carries machine id and workload model rows for machines without instances (用户反馈：注册机器不上拓扑)', () => {
    const layout = layoutTopo({
      ...input,
      machines: [
        { host: '10.0.0.9', online: false, label: 'node-a01', models: ['pipeline·qwen3-tts', 'llm·qwen-plus'] }
      ],
      instances: []
    })
    expect(layout.machines).toHaveLength(1)
    expect(layout.machines[0]).toMatchObject({
      host: '10.0.0.9',
      label: 'node-a01',
      models: ['pipeline·qwen3-tts', 'llm·qwen-plus'],
      instanceCount: 0
    })
  })
})
