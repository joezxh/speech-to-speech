import { describe, expect, it } from 'vitest'

import type { CatalogEntry } from '@/types/catalog'
import { baseline, buildPatch, MASK, resetValue } from './draft-patch'

function entry(key: string, fallback: unknown): CatalogEntry {
  return {
    key,
    stage: key.split('.')[0],
    backend: null,
    name: key.split('.')[1],
    type: 'string',
    default: fallback,
    choices: [],
    required: false,
    effect: '',
    exposure: 'basic',
    impact: '',
    change_cost: 'restart',
    risk: null,
    source_ref: '',
    source_priority: []
  }
}

const ENTRIES = [entry('vad.min_silence_ms', 500), entry('llm.api_key', ''), entry('stt.language', 'auto')]

describe('baseline', () => {
  it('prefers the draft value and falls back to the catalog default', () => {
    expect(baseline(ENTRIES, { 'vad.min_silence_ms': 700 })).toEqual({
      'vad.min_silence_ms': 700,
      'llm.api_key': '',
      'stt.language': 'auto'
    })
  })

  it('treats a stored null as "use the default"', () => {
    expect(baseline(ENTRIES, { 'stt.language': null })['stt.language']).toBe('auto')
  })
})

describe('buildPatch', () => {
  const draft = { 'vad.min_silence_ms': 700, 'llm.api_key': 'sk-live' }

  it('sends only the keys that changed', () => {
    const values = { ...baseline(ENTRIES, draft), 'stt.language': 'zh' }
    expect(buildPatch(ENTRIES, values, draft)).toEqual({ 'stt.language': 'zh' })
  })

  it('leaves an untouched mask out of the patch', () => {
    // The field still reads `***` because the user never typed a new key.
    const values = { ...baseline(ENTRIES, draft), 'llm.api_key': MASK }
    expect(buildPatch(ENTRIES, values, draft)).toEqual({})
  })

  it('sends null only when there was a draft value to clear', () => {
    const values = { ...baseline(ENTRIES, draft), 'stt.language': resetValue(ENTRIES[2], draft) }
    expect(buildPatch(ENTRIES, values, draft)).toEqual({})

    const cleared = { ...baseline(ENTRIES, draft), 'vad.min_silence_ms': resetValue(ENTRIES[0], draft) }
    expect(buildPatch(ENTRIES, cleared, draft)).toEqual({ 'vad.min_silence_ms': null })
  })
})
