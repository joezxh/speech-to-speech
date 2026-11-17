import { describe, expect, it } from 'vitest'

import { applyScenario, diffRows, rowTone, type ParamRow, type Scene } from './deploy.viewmodel'

function row(over: Partial<ParamRow> = {}): ParamRow {
  return {
    key: 'vad.min_silence_ms', expected: '700', actual: null, drift: false,
    source: 'profile', effect: 'hot', exposure: 'basic', risk: '', anchor: '',
    ...over,
  }
}

const scene: Scene = {
  name: 'latency',
  patches: { 'vad.min_silence_ms': '300', 'tts.chunk_size': '2' },
  note: 'low latency', why: 'buffers', gain: 'fast', cost: 'cpu', risk: 'vad',
}

describe('deploy viewmodel', () => {
  it('rowTone priority: drift > ops > ro > draft', () => {
    expect(rowTone(row({ drift: true, exposure: 'ops' }))).toBe('drift')
    expect(rowTone(row({ exposure: 'ops' }))).toBe('ops')
    expect(rowTone(row({ effect: 'startup' }))).toBe('ro')
    expect(rowTone(row({ effect: 'hot' }))).toBeNull()
  })

  it('applyScenario only writes keys that differ from current', () => {
    const result = applyScenario(scene, { 'vad.min_silence_ms': '300', other: 'x' })
    expect(result).toEqual({ ...scene.patches, other: 'x' })
    expect(Object.keys(result)).toContain('tts.chunk_size')
  })

  it('diffRows marks same rows where actual equals suggestion', () => {
    const rows = diffRows(scene, { 'vad.min_silence_ms': '300', 'tts.chunk_size': '4' })
    expect(rows.find((r) => r.key === 'vad.min_silence_ms')?.state).toBe('same')
    expect(rows.find((r) => r.key === 'tts.chunk_size')?.state).toBe('diff')
  })
})
