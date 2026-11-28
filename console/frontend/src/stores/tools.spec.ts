// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { toolsApi } from '@/api/tools'
import { useToolsStore } from '@/stores/tools'
import type { ToolRow } from '@/api/tools'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api/tools', () => ({
  toolsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    copy: vi.fn(),
    toggle: vi.fn(),
    invoke: vi.fn()
  }
}))

const rows: ToolRow[] = [
  {
    id: 'tool-search', name: 'Web search', type: 'web_search', description: 'search',
    endpoint: '', method: 'GET', scope: 'global', enabled: true, builtin: true, owner: '',
    params: [], config: {}, effectiveEnabled: true, writable: true,
    createdAt: null, updatedAt: null, createdBy: '', updatedBy: ''
  },
  {
    id: 'tool-custom', name: 'Private', type: 'http', description: 'hook',
    endpoint: 'https://example.com', method: 'GET', scope: 'session', enabled: true, builtin: false, owner: 'alice',
    params: [], config: {}, effectiveEnabled: null, writable: true,
    createdAt: null, updatedAt: null, createdBy: '', updatedBy: ''
  }
]

describe('tools store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(toolsApi.list).mockResolvedValue({ tools: rows } as never)
    localStorage.clear()
  })

  it('load populates rows and kpi counts', async () => {
    const store = useToolsStore()
    await store.load()
    expect(store.rows).toHaveLength(2)
    expect(store.kpi.total).toBe(2)
    expect(store.kpi.builtin).toBe(1)
  })

  it('applyFilter matches keyword, scope and enabled', async () => {
    const store = useToolsStore()
    await store.load()
    expect(store.applyFilter({ q: 'private', type: 'all', scope: 'all', on: 'all' })).toHaveLength(1)
    expect(store.applyFilter({ q: '', type: 'web_search', scope: 'all', on: 'all' })).toHaveLength(1)
    expect(store.applyFilter({ q: '', type: 'all', scope: 'session', on: 'all' })).toHaveLength(1)
  })

  it('enabledTools includes session tool when localStorage enables it', async () => {
    localStorage.setItem('s2s.tools.session.enabled', JSON.stringify({ 'tool-custom': true }))
    const store = useToolsStore()
    await store.load()
    expect(store.enabledTools.map((r) => r.id)).toEqual(['tool-search', 'tool-custom'])
  })

  it('toggle session tool writes localStorage', async () => {
    vi.mocked(toolsApi.toggle).mockResolvedValue({ ...rows[1], effectiveEnabled: null } as never)
    const store = useToolsStore()
    await store.load()
    await store.toggle('tool-custom', true)
    expect(JSON.parse(localStorage.getItem('s2s.tools.session.enabled') || '{}')['tool-custom']).toBe(true)
  })

  it('toggle builtin tool calls API', async () => {
    vi.mocked(toolsApi.toggle).mockResolvedValue({ ...rows[0], effectiveEnabled: false } as never)
    const store = useToolsStore()
    await store.load()
    await store.toggle('tool-search', false)
    expect(toolsApi.toggle).toHaveBeenCalledWith('tool-search', false)
  })
})
