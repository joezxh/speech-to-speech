import { describe, expect, it } from 'vitest'

import type { TrafficSettings } from '@/types/traffic'
import { trafficViewModel } from './trafficViewModel'

const off: TrafficSettings = {
  allocatorMode: 'off', consoleId: 'c1', seedConfigured: false, probeIntervalS: 5,
  probeTimeoutS: 2, failThreshold: 3, recoverThreshold: 2, grantTtlS: 60, usageIntervalS: 30,
  metricRetentionDays: 7, queueEnabled: false, webrtcHangupEnabled: false,
  scheduling: { policy: 'least-in-use', configurable: false, tieBreaker: 'weight-random' },
  unimplemented: ['session-stickiness', 'canary-ratio', 'routing-rules']
}

describe('trafficViewModel', () => {
  it('flags off-mode and read-only policy', () => {
    const vm = trafficViewModel(off)
    expect(vm.showOffBanner).toBe(true)
    expect(vm.policyReadOnly).toBe(true)
  })

  it('maps each unimplemented feature to a traffic.unimpl key', () => {
    const keys = trafficViewModel(off).features.map((f) => f.reasonKey)
    expect(keys).toContain('traffic.unimpl.stickiness')
    expect(trafficViewModel(off).features.every((f) => f.feature)).toBe(true)
  })
})
