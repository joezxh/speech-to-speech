import { describe, expect, it } from 'vitest'

import {
  eventRows,
  overviewKpis,
  topoRows,
  type AuditRow,
  type Instance,
  type LbStats,
  type Machine,
} from './overview.viewmodel'

const machine = (over: Partial<Machine> = {}): Machine => ({
  machineId: 'node-a01', state: 'online', role: 'agent', gpu: 'L40S', gpuTotalGb: 48, version: '1.0',
  ...over,
})
const instance = (over: Partial<Instance> = {}): Instance => ({
  instance_id: 'pipe-a', base_url: 'http://10.0.0.1:8765', machine_id: 'node-a01', status: 'online',
  ...over,
})
const lbStats: LbStats = { sticky_hit_rate: null, rules: [] }
const auditRow = (over: Partial<AuditRow> = {}): AuditRow => ({
  id: 1, at: '2026-11-17T10:00:00Z', actor: 'alice', action: 'machine.create', category: 'machine', profile: 'node-a',
  ...over,
})

describe('overview viewmodel', () => {
  it('KPIs: machines as x/y, hit rate shows 不可得 when no data', () => {
    const kpis = overviewKpis(
      [machine(), machine({ machineId: 'node-b02', state: 'pending_register' })],
      [instance()],
      lbStats,
      [auditRow()]
    )
    const machines = kpis.find((k) => k.key === 'machines')
    expect(machines?.value).toBe('1/2')
    const hit = kpis.find((k) => k.key === 'hitRate')
    expect(hit?.value).toBe('不可得')
  })

  it('KPIs: hit rate shows percent when available', () => {
    const kpis = overviewKpis([machine()], [instance()], { sticky_hit_rate: 0.75, rules: [] }, [])
    expect(kpis.find((k) => k.key === 'hitRate')?.value).toBe('75%')
  })

  it('topoRows groups instances by machine; unbound instances group alone', () => {
    const rows = topoRows(
      [machine()],
      [instance(), instance({ instance_id: 'pipe-b', machine_id: null })]
    )
    expect(rows).toHaveLength(2)
    const bound = rows.find((r) => r.machine_id === 'node-a01')
    expect(bound?.instances.map((i) => i.instance_id)).toEqual(['pipe-a'])
    const unbound = rows.find((r) => r.machine_id === null)
    expect(unbound?.instances.map((i) => i.instance_id)).toEqual(['pipe-b'])
  })

  it('eventRows takes the latest 8 by recency', () => {
    const rows = Array.from({ length: 12 }, (_, i) => auditRow({ id: i + 1, at: `2026-11-17T10:00:${String(i).padStart(2, '0')}Z` }))
    expect(eventRows(rows)).toHaveLength(8)
    expect(eventRows(rows)[0].id).toBe(12)
  })
})
