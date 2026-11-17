import { describe, expect, it } from 'vitest'

import { canAdvance, stepsFor, trimWindow, type WizardState } from './voiceWizard.viewmodel'

const baseState = (over: Partial<WizardState> = {}): WizardState => ({
  source: 'clone', name: '', audioBars: [], pending: false, window: [0, 0],
  ...over,
})

describe('voice wizard viewmodel', () => {
  it('stepsFor skips 2-4 for builtin (length 2) and 3 for design (length 4)', () => {
    expect(stepsFor('builtin')).toHaveLength(2)
    expect(stepsFor('design')).toHaveLength(4)
    expect(stepsFor('clone')).toHaveLength(5)
  })

  it('trimWindow highlights the selected window bars', () => {
    const bars = Array.from({ length: 48 }, (_, i) => i)
    const result = trimWindow(bars, 1000, 2000)
    expect(result.window).toEqual([1000, 2000])
    expect(result.bars.filter((b) => b.highlight).length).toBeGreaterThan(0)
    expect(result.bars.filter((b) => !b.highlight).length).toBeGreaterThan(0)
  })

  it('canAdvance is false while precompute is pending', () => {
    expect(canAdvance('voiceprint', baseState({ pending: true }))).toBe(false)
    expect(canAdvance('voiceprint', baseState({ pending: false, name: 'a' }))).toBe(true)
  })

  it('canAdvance requires a name on the naming step', () => {
    expect(canAdvance('naming', baseState({ name: '' }))).toBe(false)
    expect(canAdvance('naming', baseState({ name: '我的音色' }))).toBe(true)
  })
})
