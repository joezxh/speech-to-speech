import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls = vi.hoisted(() => [] as Array<{ verb: string; url: string; rest: unknown[] }>)

vi.mock('@/api/client', () => {
  const record = (verb: string) => (url: string, ...rest: unknown[]) => {
    calls.push({ verb, url, rest })
    return Promise.resolve('ok' as never)
  }
  return { api: { get: record('get'), post: record('post'), put: record('put'), delete: record('delete') } }
})

import { clustersApi } from './clusters'

describe('clustersApi', () => {
  beforeEach(() => {
    calls.length = 0
  })

  it('maps every verb onto the /clusters routes the backend exposes', async () => {
    await clustersApi.list()
    await clustersApi.events(4)
    await clustersApi.create({ name: 'gray-01', registry: 'h:8500', policy: 'rr', note: '' })
    await clustersApi.update('gray-01', { registry: 'h:8600', policy: 'lat', note: 'x' })
    await clustersApi.remove('gray-01')
    await clustersApi.switchTo('gray-01')

    expect(calls.map((c) => c.verb)).toEqual(['get', 'get', 'post', 'put', 'delete', 'post'])
    expect(calls[0].url).toBe('/clusters')
    expect(calls[1].url).toBe('/clusters/events')
    expect(calls[1].rest[0]).toEqual({ params: { limit: 4 } })
    expect(calls[3].url).toBe('/clusters/gray-01')
    expect(calls[4].url).toBe('/clusters/gray-01')
    expect(calls[5].url).toBe('/clusters/gray-01/switch')
  })

  it('url-encodes cluster names', async () => {
    await clustersApi.remove('a/b')
    expect(calls[0].url).toBe('/clusters/a%2Fb')
  })
})