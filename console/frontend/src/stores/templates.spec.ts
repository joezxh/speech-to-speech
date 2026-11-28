import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { templatesApi, type TemplateRow } from '@/api/templates'
import { useTemplatesStore } from '@/stores/templates'

vi.mock('@/api/templates', () => ({
  templatesApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() }
}))

// store 的失败路径走 i18n.global.t；测试环境用桩替掉整棵 i18n 树。
vi.mock('@/i18n', () => ({ default: { global: { t: (key: string) => key } } }))

const row = (overrides: Partial<TemplateRow>): TemplateRow => ({
  id: 1,
  name: 'GPU 24G pipeline baseline',
  effect: 'restart',
  platform: 'gpu',
  status: 'published',
  scene: 'edge',
  minVramGb: 24,
  fields: [{ key: 'llm.model_name', value: 'qwen3-8b', patch: 'llm.model_name', source: '', hot: false }],
  desc: 'restart only',
  createdAt: '2026-11-20T10:00:00Z',
  updatedAt: '2026-11-25T10:00:00Z',
  createdBy: 'alice',
  updatedBy: 'alice',
  ...overrides
})

describe('templates store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(templatesApi.list).mockResolvedValue({
      templates: [
        row({}),
        row({ id: 2, name: 'Conversation hot settings', effect: 'runtime', platform: 'npu', status: 'draft', scene: '', minVramGb: null, desc: 'hot only' }),
        row({ id: 3, name: 'NPU 32G CANN pipeline', platform: 'npu', status: 'review', scene: 'mix' })
      ],
      total: 3
    })
  })

  it('loads and derives KPI counts', async () => {
    const store = useTemplatesStore()
    await store.load()
    expect(store.rows).toHaveLength(3)
    expect(store.runtimeCount).toBe(1)
    expect(store.restartCount).toBe(2)
    expect(store.platformCount).toBe(2)
    expect(store.error).toBeNull()
  })

  it('filters in memory by effect/platform/status/q', async () => {
    const store = useTemplatesStore()
    await store.load()
    expect(store.applyFilter({ effect: 'runtime' })).toHaveLength(1)
    expect(store.applyFilter({ platform: 'npu' })).toHaveLength(2)
    expect(store.applyFilter({ status: 'review' })).toHaveLength(1)
    expect(store.applyFilter({ q: 'cann' })).toHaveLength(1)
    expect(store.applyFilter({ q: 'baseline', effect: 'restart' })).toHaveLength(1)
    expect(store.applyFilter({ q: 'baseline', effect: 'runtime' })).toHaveLength(0)
  })

  it('create refreshes the list and returns the saved row', async () => {
    vi.mocked(templatesApi.create).mockResolvedValue(row({ id: 9, name: 'new' }))
    const store = useTemplatesStore()
    await store.load()
    const saved = await store.create({
      name: 'new', effect: 'runtime', platform: 'gpu', status: 'draft',
      scene: '', minVramGb: null, fields: [], desc: ''
    })
    expect(saved?.id).toBe(9)
    // create 成功后内部重新 load：list 被拉了两次。
    expect(templatesApi.list).toHaveBeenCalledTimes(2)
    expect(store.error).toBeNull()
  })

  it('remove refreshes and surfaces failures as store error', async () => {
    const store = useTemplatesStore()
    await store.load()
    vi.mocked(templatesApi.remove).mockRejectedValue(new Error('boom'))
    expect(await store.remove(1)).toBe(false)
    expect(store.error).not.toBeNull()
    vi.mocked(templatesApi.remove).mockResolvedValue(undefined)
    expect(await store.remove(1)).toBe(true)
  })
})
