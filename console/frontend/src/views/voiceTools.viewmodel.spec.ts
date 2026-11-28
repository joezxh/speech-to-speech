// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'

import type { ToolRow } from '@/api/tools'
import { buildVoiceToolDefs, describeToolCall, serializeToolResult } from './voiceTools.viewmodel'

const row = (overrides: Partial<ToolRow> = {}): ToolRow => ({
  id: 'tool-search', name: 'Web search', type: 'web_search', description: 'Search the web',
  endpoint: '', method: 'GET', scope: 'global', enabled: true, builtin: true, owner: '',
  params: [{ k: 'query', t: 'string', req: true }], config: {}, effectiveEnabled: true, writable: true,
  createdAt: null, updatedAt: null, createdBy: '', updatedBy: '', ...overrides
})

describe('voice tools viewmodel', () => {
  it('builds tool definitions from enabled rows', () => {
    const defs = buildVoiceToolDefs([row()], false)
    expect(defs.map((d) => d.name)).toEqual(['tool-search'])
    expect(defs[0].parameters).toMatchObject({ type: 'object', required: ['query'] })
  })

  it('includes session-scope tools and camera', () => {
    const session = row({ id: 'tool-custom', name: 'Private', type: 'http', scope: 'session', effectiveEnabled: null })
    const defs = buildVoiceToolDefs([row(), session], true)
    expect(defs.map((d) => d.name)).toEqual(['tool-search', 'tool-custom', 'camera_snapshot'])
  })

  it('serializes invoke envelope to string', () => {
    const output = serializeToolResult({ mode: 'demo', provider: 'anspire', data: { results: [] } })
    expect(output).toContain('"mode":"demo"')
    expect(output).toContain('"provider":"anspire"')
  })

  it('describes tool call by name', () => {
    expect(describeToolCall({ name: 'tool-search', arguments: '{"query":"天气"}', callId: 'x' }, [row()]))
      .toBe('Search the web')
  })
})
