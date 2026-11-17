import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchRealtimeTicket } from './useRealtimeTicket'

describe('useRealtimeTicket', () => {
  afterEach(() => vi.restoreAllMocks())

  it('returns the ticket on success', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ data: { ticket: 't-1', ttl_s: 60 } }), { status: 200 })))
    expect(await fetchRealtimeTicket()).toBe('t-1')
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
