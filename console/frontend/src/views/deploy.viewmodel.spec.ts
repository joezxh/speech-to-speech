import { describe, expect, it } from 'vitest'

import {
  applyScenario,
  deployKpis,
  deployStack,
  diffRows,
  groupChips,
  groupRows,
  rowTone,
  type ParamRow,
  type Scene
} from './deploy.viewmodel'

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

describe('deploy page prototype structure (real-source only)', () => {
  const rows: ParamRow[] = [
    row({ key: 'vad.min_silence_ms', effect: 'hot', exposure: 'basic' }),
    row({ key: 'tts.chunk_size', effect: 'both', exposure: 'basic' }),
    row({ key: 'deploy.restart_policy', effect: 'startup', exposure: 'ops' }),
    row({ key: 'llm.api_key', effect: 'startup', exposure: 'ops', drift: true }),
  ]

  it('derives g4 KPIs from catalog fields, not mock constants', () => {
    expect(deployKpis(rows, 1, 'latency')).toEqual({
      params: 4, drift: 1, ops: 2, hot: 2, scene: 'latency'
    })
  })

  it('builds ALL + stage chips with counts', () => {
    expect(groupChips(rows)).toEqual([
      { group: 'ALL', count: 4 },
      { group: 'vad', count: 1 },
      { group: 'tts', count: 1 },
      { group: 'deploy', count: 1 },
      { group: 'llm', count: 1 }
    ])
    expect(groupRows(rows, 'tts').map((r) => r.key)).toEqual(['tts.chunk_size'])
    expect(groupRows(rows, 'ALL')).toHaveLength(4)
  })

  it('stack table leaves version null where no source exists', () => {
    expect(deployStack(rows)).toEqual([
      { group: 'vad', count: 1, version: null },
      { group: 'tts', count: 1, version: null },
      { group: 'deploy', count: 1, version: null },
      { group: 'llm', count: 1, version: null }
    ])
  })
})
