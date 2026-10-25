import { describe, expect, it } from 'vitest'

import { failureRateText, responseKeyShort, stageStats, stageValue } from './turn-latency-format'

describe('stageValue', () => {
  it('never prints a zero for a stage the server did not measure', () => {
    expect(stageValue(null)).toBe('不可用')
    // 千位用普通空格分组，与预览页的 `6 260 ms` 逐字一致；不走 `toLocaleString`，避开环境差异。
    expect(stageValue(6260)).toBe('6 260 ms')
  })
})

describe('stageStats', () => {
  it('keeps the `不可用 / 120 ms` shape when only p50 is missing', () => {
    expect(stageStats({ p50Ms: null, p95Ms: 120 })).toBe('不可用 / 120 ms')
    expect(stageStats({ p50Ms: 3180, p95Ms: null })).toBe('3 180 ms / 不可用')
    expect(stageStats({ p50Ms: null, p95Ms: null })).toBe('不可用')
  })
})

describe('failureRateText / responseKeyShort', () => {
  it('renders a null rate as unavailable and shortens long keys only', () => {
    expect(failureRateText(null)).toBe('不可用')
    expect(failureRateText(0.125)).toBe('12.5%')
    expect(responseKeyShort('resp_0123456789abcdef')).toBe('resp_0123456')
    expect(responseKeyShort('short')).toBe('short')
  })
})
