import { describe, expect, it } from 'vitest'

import type { InstanceSnapshot, StatusSnapshot } from '@/types/api'
import { overviewMetrics } from './overviewMetrics'

const status = {
  profile: 'prod', version: 3, status: 'live', catalogCommit: 'abc123',
  validatorMode: 'runtime', db: 'ok', pipeline: 'ok', internalTokenConfigured: true
} as unknown as StatusSnapshot
const snapshot = {
  profile: 'prod', version: 3, container: { name: '', status: '', startedAt: null, image: '', pid: null, detail: '' },
  pool: null, usage: null, alerts: ['pool_stuck:x'],
  summary: { instances_total: 2, online: 1, offline: 0, degraded: 1, draining: 0, slots_total: 8, slots_in_use: 3, slots_free: 5, pending_grants: 0 },
  instances: []
} as unknown as InstanceSnapshot

describe('overviewMetrics', () => {
  it('maps real KPIs from status + summary', () => {
    const byKey = Object.fromEntries(overviewMetrics(status, snapshot).map((m) => [m.key, m]))
    expect(byKey['overview.kpi.catalogCommit'].value).toBe('abc123')
    expect(byKey['overview.kpi.pipelineInstances'].value).toBe('2')
    expect(byKey['overview.kpi.online'].value).toBe('1')
    expect(byKey['overview.kpi.activeSessions'].value).toBe('3')
  })

  it('marks demo-only metrics as unimplemented, never mocks them', () => {
    const list = overviewMetrics(status, snapshot)
    expect(list.find((m) => m.key === 'overview.unimpl.machines')?.unimpl).toBe('S2')
    expect(list.find((m) => m.key === 'overview.unimpl.errorRate')?.unimpl).toBe('S3')
  })
})
