import { describe, expect, it } from 'vitest'

import { layoutTopo } from './topoLayout'

const full = layoutTopo({
  cluster: 'default',
  machines: [
    { host: 'host1', online: true },
    { host: 'host2', online: false }
  ],
  instances: [
    { id: 'pipe-a', status: 'online', host: 'host1' },
    { id: 'pipe-b', status: 'degraded', host: 'host1' },
    { id: 'pipe-c', status: 'offline', host: 'host2' }
  ]
})

describe('layoutTopo', () => {
  it('stacks the four layers in prototype order', () => {
    expect(full.layers.map((layer) => layer.key)).toEqual(['cluster', 'lb', 'machine', 'instance'])
    expect(full.layers.map((layer) => layer.nodes.length)).toEqual([1, 1, 2, 3])
  })

  it('spreads sibling nodes evenly and keeps y constant per layer', () => {
    const machines = full.layers[2].nodes
    expect(machines[0].x).toBeCloseTo(900 / 3)
    expect(machines[1].x).toBeCloseTo((900 / 3) * 2)
    expect(new Set(machines.map((n) => n.y)).size).toBe(1)
  })

  it('maps status to tones: online=ok, degraded=warn, everything else=bad', () => {
    expect(full.layers[2].nodes.map((n) => n.tone)).toEqual(['ok', 'bad'])
    expect(full.layers[3].nodes.map((n) => n.tone)).toEqual(['ok', 'warn', 'bad'])
  })

  it('wires cluster→lb, lb→machine, machine→instance edges', () => {
    expect(full.edges).toHaveLength(1 + 2 + 3)
    expect(full.edges[0]).toEqual({ from: 'cluster:default', to: 'lb:console' })
    expect(full.edges.some((e) => e.from === 'machine:host2' && e.to === 'instance:pipe-c')).toBe(true)
  })

  it('keeps an empty cluster renderable with muted placeholders', () => {
    const empty = layoutTopo({ cluster: 'gray-01', machines: [], instances: [] })
    expect(empty.layers[2].nodes).toEqual([
      { id: 'machine:empty', kind: 'machine', label: '', x: 450, y: 232, tone: 'muted' }
    ])
    expect(empty.layers[3].nodes.every((n) => n.tone === 'muted')).toBe(true)
  })
})