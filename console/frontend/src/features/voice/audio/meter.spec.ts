import { describe, expect, it } from 'vitest'

import { dbToPercent, fractionToDb, GATE_MAX_DB, GATE_OFF_DB, rmsToDb, SpeakingDetector } from './meter'

describe('rmsToDb', () => {
  it('turns a silent buffer into the floor, not -Infinity', () => {
    expect(rmsToDb(new Float32Array([0, 0, 0]))).toBe(-100)
    expect(rmsToDb(new Float32Array([1, -1, 1, -1]))).toBe(0)
    expect(rmsToDb(new Float32Array([0.5]))).toBeCloseTo(-6.02, 1)
  })
})

describe('dbToPercent', () => {
  it('maps the shared gate axis onto 0-100 and clamps outside it', () => {
    expect(dbToPercent(GATE_OFF_DB)).toBe(0)
    expect(dbToPercent(-3)).toBe(100)
    expect(dbToPercent(-90)).toBe(0)
    expect(dbToPercent(0)).toBe(100)
  })
})

describe('fractionToDb', () => {
  it('inverts dbToPercent and clamps the arc gap to the nearest end', () => {
    expect(fractionToDb(0)).toBe(GATE_OFF_DB)
    expect(fractionToDb(1)).toBe(GATE_MAX_DB)
    expect(fractionToDb(dbToPercent(-30) / 100)).toBeCloseTo(-30, 5)
    // 200° 弧的右侧是缺口，落进去的角度会算出 [0,1] 之外的 fraction；
    // 夹住而不是返回越界的 dB，否则拖到缺口会把门限设成 -120 dB。
    expect(fractionToDb(-0.4)).toBe(GATE_OFF_DB)
    expect(fractionToDb(1.4)).toBe(GATE_MAX_DB)
  })
})

describe('SpeakingDetector', () => {
  it('opens above -50 dB and holds for 250 ms so short gaps do not flicker', () => {
    let now = 0
    const detector = new SpeakingDetector(() => now)

    expect(detector.push(-40)).toBe(true)
    now = 100
    expect(detector.push(-80)).toBe(true)
    now = 300
    expect(detector.push(-80)).toBe(false)
  })

  it('never opens below -50 dB and resets cleanly', () => {
    let now = 0
    const detector = new SpeakingDetector(() => now)

    expect(detector.push(-60)).toBe(false)
    expect(detector.push(-30)).toBe(true)
    detector.reset()
    now = 1000
    expect(detector.push(-60)).toBe(false)
  })
})
