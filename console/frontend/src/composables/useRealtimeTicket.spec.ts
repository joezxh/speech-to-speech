import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/storage', () => ({ readToken: () => 'jwt-test' }))

import { fetchRealtimeTicket } from './useRealtimeTicket'

describe('useRealtimeTicket', () => {
  afterEach(() => vi.restoreAllMocks())

  it('returns the ticket on success and sends the bearer token', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ data: { ticket: 't-1', ttl_s: 60 } }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    expect(await fetchRealtimeTicket()).toBe('t-1')
    const calls = fetchMock.mock.calls as unknown as Array<[string, RequestInit]>
    const init = calls[0][1]
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer jwt-test')
  })

  it('returns null on 401 and never blocks the call', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('unauthorized', { status: 401 })))
    expect(await fetchRealtimeTicket()).toBeNull()
  })

  it('returns null on network failure', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('network down') }))
    expect(await fetchRealtimeTicket()).toBeNull()
  })
})
