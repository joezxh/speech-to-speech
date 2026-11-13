import { describe, expect, it } from 'vitest'

import type { ClusterRow, InstancesSummary } from '@/types/api'
import { clusterKpis } from './clusterKpis'

const row: ClusterRow = {
  name: 'default',
  registry: 'consul://h:8500',
  policy: 'least',
  note: '',
  machines_total: 2,
  machines_online: 2,
  instances_total: 4,
  healthy: true,
  updated_at: '2026-11-05T00:00:00+00:00',
  updated_by: 'alice'
}

const summary = (over: Partial<InstancesSummary> = {}): InstancesSummary => ({
  instances_total: 4,
  online: 2,
  offline: 0,
  degraded: 0,
  draining: 0,
  slots_total: 16,
  slots_in_use: 9,
  slots_free: 7,
  pending_grants: 0,
  machines_total: 2,
  machines_online: 2,
  error_rate_5m: null,
  top_error_instance: null,
  ...over
})

const byKey = (kpis: ReturnType<typeof clusterKpis>) => Object.fromEntries(kpis.map((k) => [k.key, k]))

describe('clusterKpis', () => {
  it('renders exactly the four prototype cards', () => {
    expect(clusterKpis(row, summary()).map((k) => k.key)).toEqual(['machines', 'instances', 'sessions', 'errorRate'])
  })

  it('prefers the live summary over the catalog row', () => {
    const k = byKey(clusterKpis(row, summary({ machines_online: 1 })))
    expect(k.machines.primary).toBe('1 / 2')
    expect(k.sessions.primary).toBe('9')
    expect(k.sessions.sub).toBe('7')
  })

  it('shows DASH (never 0) when the error-rate window has no samples', () => {
    const k = byKey(clusterKpis(row, summary({ error_rate_5m: null })))
    expect(k.errorRate.primary).toBe('—')
    expect(k.errorRate.sub).toBe('—')
    expect(k.errorRate.tone).toBe('muted')
    // legacy 直连：summary 整个缺席同样 DASH，machines 回落 catalog 行。
    const legacy = byKey(clusterKpis(row, null))
    expect(legacy.errorRate.primary).toBe('—')
    expect(legacy.machines.primary).toBe('2 / 2')
  })

  it('formats a sampled rate as one-decimal percent with warn tone when > 0', () => {
    const warn = byKey(clusterKpis(row, summary({ error_rate_5m: 0.0234, top_error_instance: 'pipe-b' })))
    expect(warn.errorRate.primary).toBe('2.3%')
    expect(warn.errorRate.tone).toBe('warn')
    expect(warn.errorRate.sub).toBe('pipe-b')
    const clean = byKey(clusterKpis(row, summary({ error_rate_5m: 0 })))
    expect(clean.errorRate.primary).toBe('0.0%')
    expect(clean.errorRate.tone).toBe('ok')
  })

  it('never leaks NaN into any card', () => {
    const cards = clusterKpis(null, summary({ slots_in_use: Number.NaN }))
    for (const card of cards) expect(card.primary + card.sub).not.toContain('NaN')
  })
})