import { describe, expect, it } from 'vitest'

import { bubblesScroll, orbState, toolRows, type ToolCfg } from './voice.viewmodel'

describe('voice viewmodel', () => {
  it('orbState maps five states', () => {
    expect(orbState('connected' as never)).toBe('idle')
    expect(orbState('listening' as never)).toBe('listening')
    expect(orbState('thinking' as never)).toBe('thinking')
    expect(orbState('speaking' as never)).toBe('speaking')
    expect(orbState('connecting' as never)).toBe('connecting')
  })

  it('bubblesScroll forces scroll when pinned to bottom and respects user scrollback', () => {
    expect(bubblesScroll(100, true)).toBe(true)
    expect(bubblesScroll(100, false)).toBe(false)
  })

  it('toolRows only lists enabled tools', () => {
    const tools: ToolCfg[] = [
      { name: 'search', description: 'web search' },
      { name: 'calc', description: 'calculator' },
    ]
    const rows = toolRows(tools, new Set(['search']))
    expect(rows).toHaveLength(1)
    expect(rows[0]).toEqual({ name: 'search', description: 'web search', enabled: true })
  })
})
