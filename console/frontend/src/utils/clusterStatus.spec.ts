import { describe, expect, it } from 'vitest'

import type { ClusterRow } from '@/types/api'
import { clusterStatus } from './clusterStatus'

const row = (over: Partial<ClusterRow> = {}): ClusterRow => ({
  name: 'default',
  registry: 'consul://h:8500',
  policy: 'least',
  note: '',
  machines_total: 2,
  machines_online: 2,
  instances_total: 4,
  healthy: true,
  updated_at: '2026-11-05T00:00:00+00:00',
  updated_by: 'alice',
  ...over
})

describe('clusterStatus (prototype statusTag four states)', () => {
  it('maps the four prototype states from real cluster fields', () => {
    expect(clusterStatus(row())).toBe('ok')
    expect(clusterStatus(row({ machines_online: 1 }))).toBe('warn')
    expect(clusterStatus(row({ healthy: false, machines_online: 1 }))).toBe('draining')
    expect(clusterStatus(row({ healthy: false, machines_online: 0 }))).toBe('bad')
  })

  it('renders an empty cluster as muted (spec §6 grey tag)', () => {
    expect(clusterStatus(row({ machines_total: 0, machines_online: 0 }))).toBe('muted')
    expect(clusterStatus(null)).toBe('muted')
  })

  it('renders all-pending machines as muted, not bad (待接入 ≠ 故障)', () => {
    expect(
      clusterStatus(
        row({ healthy: false, machines_online: 0, machines_pending: 2 })
      )
    ).toBe('muted')
    // 没有待接入信息（旧响应）时保持原语义：无在线 → bad
    expect(clusterStatus(row({ healthy: false, machines_online: 0 }))).toBe('bad')
  })
})
