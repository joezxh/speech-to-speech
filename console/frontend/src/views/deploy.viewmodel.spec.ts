import { describe, expect, it } from 'vitest'

import {
  applyScenario,
  deployDetailRows,
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

describe('deployDetailRows (prototype 7-field order)', () => {
  const machine = {
    machineId: 'node-a01',
    addr: '10.12.0.11:8765',
    state: 'ok',
    version: '1.1.0',
    deployedAt: '2026-11-17 12:00',
    configSource: 'console',
    gpu: 'L40S 48G',
    gpuUtilPct: 64,
    lastPushAt: '2026-11-17 12:00',
    lastPushBy: 'alice',
  }

  it('keeps the exact prototype field order and omits extra rows', () => {
    expect(deployDetailRows(machine).map((row) => row.labelKey)).toEqual([
      'machines.admin.columns.machine',
      'deploy.field.version',
      'deploy.field.deployedAt',
      'deploy.field.configSource',
      'deploy.field.gpu',
      'deploy.field.status',
      'deploy.field.lastPush',
    ])
  })

  it('formats values and tag classes exactly as the prototype', () => {
    const rows = deployDetailRows(machine)
    expect(rows[0].value).toBe('node-a01 · 10.12.0.11:8765')
    expect(rows[1]).toMatchObject({ value: '1.1.0', tagClass: 'ok' })
    expect(rows[2].value).toBe('2026-11-17 12:00')
    expect(rows[4].value).toBe('L40S 48G · 64%')
    expect(rows[6]).toMatchObject({
      valueKey: 'deploy.lastPush',
      params: { pushed: '2026-11-17 12:00', by: 'alice' }
    })
  })

  it('maps real states to prototype tag classes and leaves missing values empty', () => {
    expect(deployDetailRows({ ...machine, state: 'draining' })[1].tagClass).toBe('orange')
    expect(deployDetailRows({ ...machine, state: 'bad' })[1].tagClass).toBe('bad')
    expect(deployDetailRows({ ...machine, version: '', gpuUtilPct: null })[1].value).toBeNull()
    expect(deployDetailRows({ ...machine, gpuUtilPct: null })[4].value).toBe('L40S 48G')
    expect(deployDetailRows({ ...machine, lastPushBy: '' })[6].value).toBeNull()
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
