import { describe, expect, it } from 'vitest'

import { barTone, egressRoute, formatMs, formatPct, formatRtf, mergeInstanceStats, ratePerMinute, splitBar, trendPath } from './traffic.viewmodel'
import type { InstanceLatencyRow } from '@/api/traffic'

describe('traffic viewmodel', () => {
  it('splitBar: input=0 → aPct=0（不做除零）', () => {
    expect(splitBar(0, 500).aPct).toBe(0)
  })

  it('splitBar: 400/600 → aPct=40', () => {
    expect(splitBar(400, 600).aPct).toBe(40)
  })

  it('trendPath: peak 取 y 最小点', () => {
    const path = trendPath(
      [
        { at: 't0', input: 100, output: 50, total: 150 },
        { at: 't1', input: 10, output: 5, total: 15 },
        { at: 't2', input: 300, output: 100, total: 400 },
      ],
      400,
      100,
    )
    expect(path.peak.x).toBe(400) // t2 total=400 最高 → y 最小
    expect(path.line).toContain('M0,')
    expect(path.area).toContain('Z')
  })

  it('egressRoute: pipeline→lb 其余→direct', () => {
    expect(egressRoute('pipeline')).toBe('lb')
    expect(egressRoute('llm')).toBe('direct')
    expect(egressRoute('')).toBe('direct')
  })
})

describe('latency display helpers', () => {
  it('formatMs: null → —，数字 → "690 ms"', () => {
    expect(formatMs(null)).toBe('—')
    expect(formatMs(690)).toBe('690 ms')
  })

  it('formatPct: null → —，0.025 → "2.5%"', () => {
    expect(formatPct(null)).toBe('—')
    expect(formatPct(0.025)).toBe('2.5%')
  })

  it('formatRtf: null → —，0.41 → "0.41"', () => {
    expect(formatRtf(null)).toBe('—')
    expect(formatRtf(0.41)).toBe('0.41')
  })

  it('barTone: ≥85% 变警示色，null 不告警', () => {
    expect(barTone(85)).toBe('warn')
    expect(barTone(84.9)).toBe('ok')
    expect(barTone(null)).toBe('ok')
  })

  it('ratePerMinute: tokens/window_s 换算每分钟，无窗口 → null', () => {
    expect(ratePerMinute(7200, 3600)).toBe(120)
    expect(ratePerMinute(100, 0)).toBeNull()
  })

  it('mergeInstanceStats: 按 instance_id 合并 TTFT/RTF/错误率，缺数据给 null', () => {
    const rows = [
      { instance_id: 'pipe-a', base_url: 'u1', status: 'online' },
      { instance_id: 'pipe-b', base_url: 'u2', status: 'offline' },
    ]
    const stats: InstanceLatencyRow[] = [
      { instance_id: 'pipe-a', ttft_ms: 690, rtf: 0.41, err_rate: 0.1 },
    ]
    const merged = mergeInstanceStats(rows, stats)
    expect(merged[0].ttft_ms).toBe(690)
    expect(merged[0].rtf).toBe(0.41)
    expect(merged[0].err_rate).toBe(0.1)
    expect(merged[1].ttft_ms).toBeNull()
    expect(merged[1].rtf).toBeNull()
    expect(merged[1].err_rate).toBeNull()
  })

  it('mergeInstanceStats: stats=null → 全部 null，不抛错', () => {
    const merged = mergeInstanceStats([{ instance_id: 'x', base_url: '', status: 'online' }], null)
    expect(merged[0].ttft_ms).toBeNull()
  })
})
