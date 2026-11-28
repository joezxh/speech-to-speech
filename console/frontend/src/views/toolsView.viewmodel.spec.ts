// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'

import type { ToolRow } from '@/api/tools'
import { applyToolFilter, toolKpis, toolParamText } from './tools.viewmodel'

const row = (overrides: Partial<ToolRow> = {}): ToolRow => ({
  id: 't', name: 'T', type: 'http', description: '', endpoint: '', method: 'GET',
  scope: 'global', enabled: true, builtin: false, owner: '', params: [], config: {},
  effectiveEnabled: true, writable: true, createdAt: null, updatedAt: null, createdBy: '', updatedBy: '',
  ...overrides
})

const rows: ToolRow[] = [
  row({ id: 'tool-search', name: 'Web search', type: 'web_search', builtin: true, effectiveEnabled: true }),
  row({ id: 'tool-weather', name: 'Weather', type: 'weather', builtin: true, effectiveEnabled: false }),
  row({ id: 'tool-kb', name: 'KB', type: 'kb', builtin: true, scope: 'tenant', effectiveEnabled: false }),
  row({ id: 'tool-custom', name: 'Mine', type: 'http', effectiveEnabled: true })
]

describe('tools viewmodel', () => {
  it('filters by keyword', () => {
    expect(applyToolFilter(rows, { q: '天气', type: 'all', scope: 'all', on: 'all' })).toHaveLength(0)
    expect(applyToolFilter(rows, { q: 'weather', type: 'all', scope: 'all', on: 'all' })).toHaveLength(1)
  })

  it('computes KPIs', () => {
    expect(toolKpis(rows)).toEqual({ total: 4, on: 2, builtin: 3, custom: 1 })
  })

  it('counts session tools from localStorage', () => {
    const session = row({ id: 's1', scope: 'session', effectiveEnabled: null, enabled: true })
    expect(toolKpis([session])).toEqual({ total: 1, on: 0, builtin: 0, custom: 1 })
    expect(toolKpis([session], { s1: true })).toEqual({ total: 1, on: 1, builtin: 0, custom: 1 })
  })

  it('formats params', () => {
    expect(toolParamText(row({ params: [{ k: 'city', t: 'string', req: true }] }))).toBe('city:string!')
    expect(toolParamText(row())).toBe('—')
  })
})
