import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMock = vi.hoisted(() => ({
  list: vi.fn(),
  events: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  switchTo: vi.fn()
}))

vi.mock('@/api/clusters', () => ({ clustersApi: apiMock }))
vi.mock('@/utils/storage', () => {
  const bag = new Map<string, string>()
  return {
    readCluster: () => bag.get('cluster') ?? 'default',
    saveCluster: (v: string) => void bag.set('cluster', v)
  }
})

import { AppError } from '@/api/client'
import { useClusterStore } from './cluster'
import type { ClusterRow } from '@/types/api'

const row = (name: string): ClusterRow => ({
  name,
  registry: 'consul://h:8500',
  policy: 'least',
  note: '',
  machines_total: 2,
  machines_online: 2,
  instances_total: 4,
  healthy: true,
  updated_at: '2026-11-05T00:00:00+00:00',
  updated_by: 'alice'
})

describe('cluster store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('keeps a stored current cluster when it still exists', async () => {
    apiMock.list.mockResolvedValue([row('default'), row('gray-01')])
    const store = useClusterStore()
    await store.load()
    expect(store.current).toBe('default')
  })

  it('falls back to the first cluster when the stored one is stale', async () => {
    apiMock.list.mockResolvedValue([row('gray-01'), row('default')])
    const store = useClusterStore()
    store.current = 'ghost-99'
    await store.load()
    expect(store.current).toBe('gray-01')
  })

  it('dedupes concurrent loads into one request', async () => {
    let resolve!: (rows: ClusterRow[]) => void
    apiMock.list.mockReturnValue(new Promise((r) => { resolve = r }))
    const store = useClusterStore()
    const first = store.load()
    const second = store.load()
    resolve([row('default')])
    await Promise.all([first, second])
    expect(apiMock.list).toHaveBeenCalledTimes(1)
  })

  it('does not switch when the server rejects (audit recorded error)', async () => {
    apiMock.switchTo.mockRejectedValue(new AppError('cluster_not_found', 'missing'))
    const store = useClusterStore()
    const ok = await store.switchTo('ghost')
    expect(ok).toBe(false)
    expect(store.current).toBe('default')
    expect(store.error?.code).toBe('cluster_not_found')
  })

  it('reloads the list after remove so a deleted current falls back', async () => {
    apiMock.list.mockResolvedValue([row('default')])
    apiMock.remove.mockResolvedValue({ name: 'gray-01', deleted: true })
    const store = useClusterStore()
    await store.load()
    store.current = 'default'
    await store.remove('default')
    expect(apiMock.list).toHaveBeenCalledTimes(2)
  })
})