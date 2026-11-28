import { describe, expect, it } from 'vitest'

import type { TemplateRow } from '@/api/templates'
import {
  checkTemplateHardware,
  inferEffect,
  snapshotFields,
  templateActualRows
} from './templatePanel.viewmodel'

const template = (overrides: Partial<TemplateRow> = {}): TemplateRow => ({
  id: 1,
  name: 'GPU 24G baseline',
  effect: 'restart',
  platform: 'gpu',
  status: 'published',
  scene: 'edge',
  minVramGb: 24,
  fields: [
    { key: 'vad.min_silence_ms', value: '400', patch: 'vad.min_silence_ms', source: '', hot: false },
    { key: 'llm.model_name', value: 'qwen3-8b', patch: 'llm.model_name', source: '', hot: false }
  ],
  desc: '',
  createdAt: null,
  updatedAt: null,
  createdBy: '',
  updatedBy: '',
  ...overrides
})

describe('checkTemplateHardware', () => {
  const machine = { machineId: 'node-a01', platform: 'gpu', driver: 'cu130', gpuTotalGb: 24 }

  it('passes when platform matches and vram meets the bar', () => {
    expect(checkTemplateHardware(template(), machine)).toEqual({
      platformOk: true, vramOk: true, ok: true, reasons: []
    })
  })

  it('flags platform mismatch', () => {
    const check = checkTemplateHardware(template(), { ...machine, platform: 'npu' })
    expect(check.ok).toBe(false)
    expect(check.reasons).toEqual(['panel.check.platformMismatch'])
  })

  it('flags short vram and treats unknown vram as not-ok', () => {
    expect(checkTemplateHardware(template({ minVramGb: 48 }), machine).reasons).toEqual(['panel.check.vramShort'])
    expect(checkTemplateHardware(template({ minVramGb: 48 }), { ...machine, gpuTotalGb: null }).reasons).toEqual([
      'panel.check.vramUnknown'
    ])
  })

  it('templates without a vram bar skip the vram gate', () => {
    expect(checkTemplateHardware(template({ minVramGb: null }), machine).vramOk).toBe(true)
  })
})

describe('templateActualRows', () => {
  it('matches stringified values and marks unknown actual as null', () => {
    const rows = templateActualRows(template(), { 'vad.min_silence_ms': '400', 'llm.model_name': 'qwen3-32b' })
    expect(rows[0]).toEqual({ field: rows[0].field, actual: '400', match: true })
    expect(rows[1]).toEqual({ field: rows[1].field, actual: 'qwen3-32b', match: false })
    const empty = templateActualRows(template(), {})
    expect(empty[0].match).toBeNull()
  })
})

describe('snapshotFields + inferEffect', () => {
  it('prefers draft values, drops empty, infers effect from hot coverage', () => {
    const fields = snapshotFields(
      ['a.x', 'b.y', 'c.z'],
      { 'a.x': 'draft-1', 'c.z': '' },
      { 'b.y': 'actual-2', 'c.z': 'actual-3' }
    )
    expect(fields).toEqual([{ key: 'a.x', value: 'draft-1' }, { key: 'b.y', value: 'actual-2' }])
    expect(inferEffect(fields, new Set(['a.x', 'b.y']))).toBe('runtime')
    expect(inferEffect(fields, new Set(['a.x']))).toBe('restart')
    expect(inferEffect([], new Set(['a.x']))).toBe('restart')
  })
})
