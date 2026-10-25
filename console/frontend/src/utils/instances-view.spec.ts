import { describe, expect, it } from 'vitest'
import { capacityPercent, dedupeByLatestObserver, statusColor, statusLabelKey } from './instances-view'
import type { InstanceMetricPoint, InstanceRow } from '@/types/api'

const point = (over: Partial<InstanceMetricPoint>): InstanceMetricPoint => ({
  observedAt: '2026-10-26T08:00:00Z', observedBy: 'console-1', kind: 'sample', status: 'online',
  size: 4, inUse: 1, free: 3, stuck: 0, probeMs: 10, allocOk: 0, allocFailNoInstance: 0,
  allocFailInstance503: 0, evictCount: 0, recoverCount: 0, ...over,
})

const row = (over: Partial<InstanceRow>): InstanceRow => ({
  instance_id: 'pipe-a', base_url: 'http://a:8765', status: 'online', weight: 1,
  enabled: true, drain_requested: false, size: 4, in_use: 1, free: 3, stuck: 0,
  probe_ms: 10, p95_probe_ms: 20, units: [], last_error: '', observed_by: 'console-1',
  declared_mismatch: false, ...over,
})

describe('instances-view', () => {
  it('maps every instance-level status to a color and an i18n key', () => {
    for (const status of ['unknown', 'online', 'degraded', 'offline', 'draining']) {
      expect(statusColor(status)).toMatch(/^(default|green|orange|red|blue)$/)
      expect(statusLabelKey(status)).toBe(`instances.status.${status}`)
    }
  })

  it('dedupes multi-console samples by latest observer instead of summing', () => {
    const rows = dedupeByLatestObserver([
      point({ observedBy: 'console-1', evictCount: 1 }),
      point({ observedBy: 'console-2', evictCount: 1 }),
    ])
    expect(rows).toHaveLength(1) // 同一实例同时刻两 console 只留一行，避免 ×N（spec §10）
  })

  it('keeps the latest sample within a second bucket', () => {
    const rows = dedupeByLatestObserver([
      point({ observedAt: '2026-10-26T08:00:00Z', observedBy: 'console-1', inUse: 1 }),
      point({ observedAt: '2026-10-26T08:00:00.500Z', observedBy: 'console-2', inUse: 2 }),
    ])
    expect(rows).toHaveLength(1)
    expect(rows[0].inUse).toBe(2)
  })

  it('computes capacity percent from in_use over size', () => {
    expect(capacityPercent(row({ size: 4, in_use: 1 }))).toBe(25)
    expect(capacityPercent(row({ size: 0, in_use: 0 }))).toBe(0)
    expect(capacityPercent(row({ size: null, in_use: null }))).toBe(0)
  })
})
