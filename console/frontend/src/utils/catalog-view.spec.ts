import { describe, expect, it } from 'vitest'

import type { CatalogEntry } from '@/types/catalog'
import { countLabel, dedupe, groupByStage, isReadOnlyRow } from './catalog-view'

describe('catalog-view', () => {
  const entry = (stage: string, backend: string | null, name: string): CatalogEntry =>
    ({
      key: `${stage}/${backend ?? '-'}/${name}`,
      stage,
      backend,
      name,
      type: 'string',
      default: null,
      choices: [],
      required: false,
      source_priority: ['yaml'],
      effect: 'startup',
      exposure: 'advanced',
      impact: 'pipeline',
      change_cost: 'restart',
      risk: null,
      source_ref: 'test:test'
    }) as CatalogEntry

  it('merges the three duplicate names and keeps the documented winner', () => {
    const result = dedupe([
      entry('client', null, 'log_transcripts'),
      entry('runtime', null, 'log_transcripts'),
      entry('llm', null, 'model_name'),
      entry('llm', 'responses-api', 'model_name'),
      entry('llm', 'chat-completions', 'responses_api_reasoning_effort'),
      entry('llm', 'responses-api', 'responses_api_reasoning_effort')
    ])

    expect(result.items.map((item) => `${item.stage}/${item.backend}/${item.name}`)).toEqual([
      'runtime/null/log_transcripts',
      'llm/null/model_name',
      'llm/responses-api/responses_api_reasoning_effort'
    ])
    expect(countLabel(6, result)).toBe('6 条 · 3 个唯一名 · 2 个多后端字段')
  })

  it('groups by stage then backend without reordering', () => {
    const groups = groupByStage([
      entry('vad', null, 'thresh'),
      entry('vad', 'firered', 'vad_firered_threshold'),
      entry('client', null, 'api_key')
    ])

    expect(groups.map((group) => group.key)).toEqual(['vad::', 'vad::firered', 'client::'])
    expect(groups.map((group) => group.items.length)).toEqual([1, 1, 1])
    expect(groups.filter((group) => group.readOnly).map((group) => group.stage)).toEqual(['client'])
  })

  it('keeps read-only stages visible instead of hiding them', () => {
    // 隐藏 = 运维以为参数不存在；只读 = 运维知道它存在但轮不到控制台改（§6.1）。
    const groups = groupByStage([entry('deploy', null, 'max_config_bytes')])
    expect(groups).toHaveLength(1)
    expect(groups[0].readOnly).toBe(true)
  })

  it('treats a fixed entry as a read-only row wherever it sits', () => {
    // §7.3：`type=fixed` 无论 exposure 为何都渲染只读行，不套用分级表。
    expect(isReadOnlyRow({ ...entry('runtime', null, 'chunk_samples'), type: 'fixed' })).toBe(true)
    expect(isReadOnlyRow(entry('env', null, 'HF_HUB_OFFLINE'))).toBe(true)
    expect(isReadOnlyRow(entry('vad', null, 'thresh'))).toBe(false)
  })
})
